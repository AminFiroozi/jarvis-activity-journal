#!/usr/bin/env python3
"""Analyze representative screenshots through an OpenAI-compatible vision endpoint."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request

try:
    from ocr import extract_text
    from screenshot_fingerprint import deduplicate_images
except ImportError:  # Supports importing as ``src.analyze_screenshots`` in tests.
    from src.ocr import extract_text
    from src.screenshot_fingerprint import deduplicate_images


DEFAULT_PROMPTS = pathlib.Path(__file__).parents[1] / "config" / "prompts.json"


def load_prompts(path: pathlib.Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        prompts = json.load(handle)
    if not isinstance(prompts, dict) or not isinstance(prompts.get("contexts"), dict):
        raise ValueError("Prompt configuration must contain a contexts object")
    return prompts


def select_prompt_context(context: str, prompts: dict) -> dict:
    normalized = (context or "unknown").strip().lower()
    aliases = {"shell": "terminal", "powershell": "terminal", "editor": "ide", "chat": "messaging"}
    normalized = aliases.get(normalized, normalized)
    contexts = prompts["contexts"]
    selected = contexts.get(normalized, contexts["unknown"])
    base = prompts.get("base", {})
    return {
        "name": normalized if normalized in contexts else "unknown",
        "instructions": f"{base.get('instructions', '')} {selected.get('instructions', '')}".strip(),
        "output": base.get("output", {}),
    }


def build_prompt(context: str, prompts: dict, ocr_result: dict | None = None) -> str:
    selected = select_prompt_context(context, prompts)
    evidence = ocr_result or {"available": False, "regions": [], "reason": "not run"}
    ocr_lines = [
        f"- {region.get('text', '')} (confidence={region.get('confidence', 0):.2f}, box={region.get('box', [])})"
        for region in evidence.get("regions", [])
    ]
    ocr_text = "\n".join(ocr_lines) if ocr_lines else f"OCR unavailable: {evidence.get('reason', 'no regions')}"
    schema = json.dumps(selected["output"], ensure_ascii=False)
    return f"""Analyze this computer screenshot for a personal activity journal.
Context hint: {selected['name']}
{selected['instructions']}

OCR evidence is supplemental and may be wrong; use the screenshot as the source of truth:
{ocr_text}

Return only valid JSON matching this schema: {schema}
Use empty arrays and lower confidence when evidence is unclear. Do not include secrets."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--max-screenshots", type=int, default=12)
    parser.add_argument("--dedupe-threshold", type=int, default=4)
    parser.add_argument("--context", default="unknown", choices=("terminal", "browser", "ide", "messaging", "unknown"))
    parser.add_argument("--prompts", type=pathlib.Path, default=DEFAULT_PROMPTS)
    return parser.parse_args()


def select_representative_images(folder: pathlib.Path, limit: int) -> list[pathlib.Path]:
    images = sorted(folder.glob("*.jpg"), key=lambda path: path.stat().st_mtime)
    if len(images) <= limit:
        return images
    indexes = [round(index * (len(images) - 1) / (limit - 1)) for index in range(limit)]
    return [images[index] for index in indexes]


def call_vision(endpoint: str, model: str, api_key: str | None, image: pathlib.Path, context: str = "unknown", prompts: dict | None = None) -> dict:
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    prompt_config = prompts or load_prompts(DEFAULT_PROMPTS)
    ocr_result = extract_text(image)
    body = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": build_prompt(context, prompt_config, ocr_result)},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ]}],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {api_key}"} if api_key else {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    content = str(content).strip().removeprefix("```json").removesuffix("```").strip()
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Vision response was not a JSON object")
    return parsed


def main() -> int:
    args = parse_args()
    journal = pathlib.Path(args.journal_root)
    screenshot_dir = journal / "screenshots" / args.date
    raw_dir = journal / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output = raw_dir / f"visual-{args.date}.jsonl"
    status = raw_dir / f"visual-{args.date}.status.json"
    images = select_representative_images(screenshot_dir, max(1, args.max_screenshots)) if screenshot_dir.exists() else []
    images = deduplicate_images(images, threshold=max(0, args.dedupe_threshold))
    if not images:
        status.write_text(json.dumps({"date": args.date, "status": "no-screenshots"}) + "\n", encoding="utf-8")
        return 0

    api_key = os.environ.get(args.api_key_env)
    prompts = load_prompts(args.prompts)
    results = []
    failures = []
    for image in images:
        try:
            analysis = call_vision(args.endpoint, args.model, api_key, image, args.context, prompts)
            results.append({"timestamp": dt.datetime.fromtimestamp(image.stat().st_mtime, dt.timezone.utc).isoformat(), "source": "screenshot-vision", "screenshot": str(image), "analysis": analysis})
        except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as error:
            failures.append({"screenshot": str(image), "error": str(error)})
    with output.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    status.write_text(json.dumps({"date": args.date, "status": "complete" if not failures else "partial", "analyzed": len(results), "failed": failures}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"analyzed": len(results), "failed": len(failures), "output": str(output)}))
    return 0 if results or not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
