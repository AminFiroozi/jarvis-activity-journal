"""Render llm-context/latest.md — raw, verbatim recent evidence for an LLM assistant to read."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
from collections import Counter


def read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def local_time(value: str, fmt: str) -> str:
    try:
        return dt.datetime.fromisoformat(value).strftime(fmt)
    except (ValueError, TypeError):
        return value or ""


def render(journal_root: pathlib.Path, date: str) -> str:
    raw = journal_root / "raw"
    activity_path = raw / f"activity-{date}.jsonl"
    if not activity_path.exists():
        return f"# Activity Context\n\nNo local activity events found for {date}."

    events = read_jsonl(activity_path)
    content_events = read_jsonl(raw / f"content-{date}.jsonl")
    visual_events = read_jsonl(raw / f"visual-{date}.jsonl")
    screenshot_dir = journal_root / "screenshots" / date
    screenshot_count = len(list(screenshot_dir.glob("*.jpg"))) if screenshot_dir.exists() else 0

    lines = [
        "# Activity Context for Jarvis",
        "",
        f"> Date: {date}",
        "> Source: local metadata collector",
        "> Treat observations as evidence; do not claim intent unless explicitly supported.",
        "",
        "## Observed applications",
        "",
    ]
    app_counts = Counter(event["process"] for event in events if event.get("source") == "foreground-window" and event.get("process"))
    if app_counts:
        for process, count in app_counts.most_common():
            lines.append(f"- {process}: {count} samples")
    else:
        lines.append("- None")

    lines.extend(["", "## Observed project evidence", ""])
    projects = [event for event in events if event.get("source") == "git-project"]
    if projects:
        for project in projects:
            lines.append(
                f"- Path: {project.get('projectPath')}; branch: {project.get('branch')}; "
                f"changed files: {project.get('changedFileCount')}; latest commit: {project.get('latestCommit')} {project.get('latestCommitMessage')}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Captured content", ""])
    lines.append(f"- Focused-content events: {len(content_events)}")
    lines.append(f"- Full-desktop screenshots: {screenshot_count}")
    lines.append(f"- Vision-analyzed screenshots: {len(visual_events)}")
    for event in content_events[-12:]:
        time_label = local_time(event.get("localTimestamp", ""), "%H:%M:%S")
        lines.extend([f"### {time_label} — {event.get('process')}", "", "```text", event.get("content", ""), "```", ""])

    lines.extend(["## Vision observations", ""])
    if visual_events:
        for event in visual_events[-12:]:
            analysis = event.get("analysis") or {}
            time_label = local_time(event.get("timestamp", ""), "%H:%M")
            lines.append(f"- {time_label} — {analysis.get('activity_type')}: {analysis.get('summary')} (confidence: {analysis.get('confidence')})")
    else:
        lines.append("- No vision observations are available yet. Configure a vision provider and run the analysis pipeline.")

    lines.extend(["", "## Recent windows", ""])
    window_events = [event for event in events if event.get("source") == "foreground-window"]
    for event in window_events[-30:]:
        time_label = local_time(event.get("localTimestamp", ""), "%H:%M:%S")
        title = event.get("windowTitle") or "[untitled]"
        lines.append(f"- {time_label} — {event.get('process')} — {title} — active: {event.get('active')}")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_directory = args.journal_root / "llm-context"
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / "latest.md"
    output_path.write_text(render(args.journal_root, args.date), encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
