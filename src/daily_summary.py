"""Daily job: retention cleanup, final vision pass, deterministic daily scaffold, LLM narrative refresh."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
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


def render_daily_scaffold(journal_root: pathlib.Path, date: str) -> str:
    events = read_jsonl(journal_root / "raw" / f"activity-{date}.jsonl")
    window_events = [event for event in events if event.get("source") == "foreground-window" and event.get("process")]
    active_events = [event for event in window_events if event.get("active") is True]
    app_counts = Counter(event["process"] for event in active_events)
    project_events = [event for event in events if event.get("source") == "git-project"]
    first = window_events[0]["localTimestamp"][11:16] if window_events else "-"
    last = window_events[-1]["localTimestamp"][11:16] if window_events else "-"

    lines = [
        f"# Automatic Activity Journal — {date}",
        "",
        "> Generated from local metadata. This records observed computer activity; it does not prove intent or comprehension.",
        "",
        "## Collection window",
        "",
        f"- Samples: {len(events)}",
        f"- Approximate observed window: {first}–{last}",
        f"- Active samples: {len(active_events)}",
        "",
        "## Applications",
        "",
    ]
    if app_counts:
        lines.extend(["| Application | Samples | Approx. minutes |", "|---|---:|---:|"])
        for process, count in app_counts.most_common():
            lines.append(f"| {process} | {count} | {round(count / 60, 1)} |")
    else:
        lines.append("_No foreground application samples were collected._")

    lines.extend(["", "## Project evidence", ""])
    if project_events:
        for event in project_events:
            lines.append(
                f"- **{event.get('projectPath')}** — branch `{event.get('branch')}`, "
                f"changed files: {event.get('changedFileCount')}, latest commit: `{event.get('latestCommit')}` {event.get('latestCommitMessage')}"
            )
    else:
        lines.append("_No configured Git project evidence was collected._")

    lines.extend([
        "",
        "## Limitations",
        "",
        "- No screenshots, audio, webcam, keystrokes, clipboard, browser contents, document contents, or diffs are included.",
        "- Application time is estimated from sampling frequency and excludes detected idle samples.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    subprocess.run([sys.executable, "-m", "src.retention", "--journal-root", str(args.journal_root), "--config", str(args.config)], cwd=pathlib.Path(__file__).parents[1])
    subprocess.run([sys.executable, "-m", "src.analyze_screenshots", "--journal-root", str(args.journal_root), "--config", str(args.config), "--date", args.date], cwd=pathlib.Path(__file__).parents[1])

    daily_path = args.journal_root / "daily" / f"{args.date}.md"
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.write_text(render_daily_scaffold(args.journal_root, args.date), encoding="utf-8")

    subprocess.run([sys.executable, "-m", "src.build_llm_context", "--journal-root", str(args.journal_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[1])
    result = subprocess.run([sys.executable, "-m", "src.synthesize_journal", "--journal-root", str(args.journal_root), "--config", str(args.config), "--date", args.date], cwd=pathlib.Path(__file__).parents[1])
    print(str(daily_path))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
