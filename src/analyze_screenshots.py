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


PROMPT = """Analyze this computer screenshot for a personal activity journal.
Return only valid JSON with these fields:
{
  "summary": "one concise sentence describing the visible activity",
  "applications": ["visible app names"],
  "projects": ["visible project or website names"],
  "activity_type": "coding|browsing|chatting|meeting|media|administration|other",
  "confidence": 0.0
}
Do not guess passwords, private message contents, or identities. If unclear, use empty arrays and lower confidence."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--max-screenshots", type=int, default=12)
    return parser.parse_args()


def select_representative_images(folder: pathlib.Path, limit: int) -> list[pathlib.Path]:
    images = sorted(folder.glob("*.jpg"), key=lambda path: path.stat().st_mtime)
    if len(images) <= limit:
        return images
    indexes = [round(index * (len(images) - 1) / (limit - 1)) for index in range(limit)]
    return [images[index] for index in indexes]


def call_vision(endpoint: str, model: str, api_key: str | None, image: pathlib.Path) -> dict:
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    body = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
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
    if not images:
        status.write_text(json.dumps({"date": args.date, "status": "no-screenshots"}) + "\n", encoding="utf-8")
        return 0

    api_key = os.environ.get(args.api_key_env)
    results = []
    failures = []
    for image in images:
        try:
            analysis = call_vision(args.endpoint, args.model, api_key, image)
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
