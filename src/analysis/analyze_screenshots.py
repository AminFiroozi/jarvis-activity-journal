#!/usr/bin/env python3
"""Analyze representative screenshots through an OpenAI-compatible vision endpoint."""

from __future__ import annotations

import argparse
import base64
import bisect
import datetime as dt
import hashlib
import json
import pathlib

from src.providers.model_client import ProviderError, call_chat_completions, resolve_provider
from src.analysis.ocr import extract_text
from src.infra.processing_queue import FileJobQueue
from src.analysis.screenshot_fingerprint import deduplicate_images
from src.infra.heartbeat import write_heartbeat


DEFAULT_PROMPTS = pathlib.Path(__file__).parents[2] / "config" / "prompts.json"

_CONTEXT_APP_HINTS = {
    "terminal": ("powershell", "pwsh", "cmd", "windowsterminal", "conhost", "bash", "wt", "wsl", "termius", "putty"),
    "browser": ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi"),
    "ide": ("code", "devenv", "pycharm", "idea", "webstorm", "sublime_text", "cursor", "clion", "rider"),
    "messaging": ("telegram", "doolgram", "discord", "slack", "outlook", "teams", "whatsapp", "signal"),
}


def infer_context(app_name: str) -> str:
    lowered = (app_name or "").lower()
    for context, hints in _CONTEXT_APP_HINTS.items():
        if any(hint in lowered for hint in hints):
            return context
    return "unknown"


def load_window_events(journal: pathlib.Path, date: str) -> list[tuple[float, str]]:
    """Return sorted (epoch_seconds, process) pairs from foreground-window events for the date."""
    path = journal / "raw" / f"activity-{date}.jsonl"
    events: list[tuple[float, str]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("source") != "foreground-window":
            continue
        timestamp, process = record.get("timestamp"), record.get("process")
        if not timestamp or not process:
            continue
        try:
            epoch = dt.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        events.append((epoch, process))
    events.sort(key=lambda item: item[0])
    return events


def nearest_context(window_events: list[tuple[float, str]], target_epoch: float, fallback: str) -> str:
    if not window_events:
        return fallback
    times = [item[0] for item in window_events]
    index = bisect.bisect_left(times, target_epoch)
    candidates = [candidate for candidate in (index - 1, index) if 0 <= candidate < len(window_events)]
    if not candidates:
        return fallback
    best = min(candidates, key=lambda candidate: abs(window_events[candidate][0] - target_epoch))
    return infer_context(window_events[best][1])


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
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--context", default="unknown", choices=("terminal", "browser", "ide", "messaging", "unknown"))
    parser.add_argument("--prompts", type=pathlib.Path, default=DEFAULT_PROMPTS)
    return parser.parse_args()


def job_id_for(image: pathlib.Path) -> str:
    digest = hashlib.sha256(str(image).encode("utf-8")).hexdigest()[:12]
    return f"{image.stat().st_mtime:015.3f}-{digest}"


def _has_pending_jobs(queue: FileJobQueue, kind: str) -> bool:
    for path in (queue.root / "pending").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("kind") == kind:
            return True
    return False


def load_analyzed_screenshots(output: pathlib.Path) -> set[str]:
    if not output.exists():
        return set()
    analyzed: set[str] = set()
    with output.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                analyzed.add(json.loads(line)["screenshot"])
            except (json.JSONDecodeError, KeyError):
                continue
    return analyzed


def call_vision(provider: dict, image: pathlib.Path, context: str = "unknown", prompts: dict | None = None) -> dict:
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    prompt_config = prompts or load_prompts(DEFAULT_PROMPTS)
    ocr_result = extract_text(image)
    messages = [{"role": "user", "content": [
        {"type": "text", "text": build_prompt(context, prompt_config, ocr_result)},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
    ]}]
    content = call_chat_completions(provider, messages, temperature=0)
    content = content.strip().removeprefix("```json").removesuffix("```").strip()
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Vision response was not a JSON object")
    return parsed


def main() -> int:
    args = parse_args()
    journal = pathlib.Path(args.journal_root)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    analyzer_config = config.get("screenshotAnalyzer") or {}
    screenshot_config = (config.get("collectors") or {}).get("screenshot") or {}
    screenshot_dir = journal / "screenshots" / args.date
    raw_dir = journal / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output = raw_dir / f"visual-{args.date}.jsonl"
    status = raw_dir / f"visual-{args.date}.status.json"
    all_images = sorted(screenshot_dir.glob("*.jpg"), key=lambda path: path.stat().st_mtime) if screenshot_dir.exists() else []
    analyzed = load_analyzed_screenshots(output)
    candidates = [image for image in all_images if str(image) not in analyzed]
    candidates = deduplicate_images(candidates, threshold=max(0, int(screenshot_config.get("dedupeHammingThreshold", 4))))

    queue = FileJobQueue(journal / "queue")
    window_events = load_window_events(journal, args.date)
    for image in candidates:
        context = nearest_context(window_events, image.stat().st_mtime, args.context)
        queue.enqueue("vision", {"screenshot": str(image), "date": args.date, "context": context}, job_id=job_id_for(image))

    max_per_run = max(1, int(analyzer_config.get("maxScreenshotsPerRun", 12)))
    if not _has_pending_jobs(queue, "vision"):
        status.write_text(json.dumps({"date": args.date, "status": "no-screenshots"}) + "\n", encoding="utf-8")
        return 0

    try:
        provider = resolve_provider(config, "screenshotAnalyzer")
    except ProviderError as error:
        status.write_text(json.dumps({"date": args.date, "status": "failed", "error": str(error)}) + "\n", encoding="utf-8")
        print(f"Screenshot analysis failed: {error}")
        return 1
    prompts = load_prompts(args.prompts)
    max_attempts = int(analyzer_config.get("maxAttempts", 5))
    retry_delay_seconds = int(analyzer_config.get("retryDelaySeconds", 60))

    results = []
    failures = []
    processed = 0
    attempted_this_run: set[str] = set()
    while processed < max_per_run:
        job = queue.claim(kind="vision", exclude_ids=attempted_this_run)
        if job is None:
            break
        attempted_this_run.add(job["id"])
        processed += 1
        image = pathlib.Path(job["payload"]["screenshot"])
        context = job["payload"].get("context", "unknown")
        try:
            analysis = call_vision(provider, image, context, prompts)
            queue.complete(job["id"], {"ok": True})
            results.append({"timestamp": dt.datetime.fromtimestamp(image.stat().st_mtime, dt.timezone.utc).isoformat(), "source": "screenshot-vision", "screenshot": str(image), "analysis": analysis})
        except (OSError, ValueError, KeyError, json.JSONDecodeError, ProviderError) as error:
            outcome = queue.fail(job["id"], str(error), max_attempts=max_attempts, retry_delay_seconds=retry_delay_seconds)
            failures.append({"screenshot": str(image), "error": str(error), "queueStatus": outcome["status"], "attempts": outcome["attempts"]})

    with output.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    remaining = sum(1 for _ in (journal / "queue" / "pending").glob("*.json"))
    status.write_text(json.dumps({"date": args.date, "status": "complete" if not failures else "partial", "analyzed": len(results), "failed": failures, "queuedRemaining": remaining}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"analyzed": len(results), "failed": len(failures), "queuedRemaining": remaining, "output": str(output)}))
    if results or not failures:
        write_heartbeat(journal, "vision-analysis", "success", items_processed=len(results))
        return 0
    write_heartbeat(journal, "vision-analysis", "failed", items_processed=len(results), error_message=failures[0]["error"] if failures else None)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
