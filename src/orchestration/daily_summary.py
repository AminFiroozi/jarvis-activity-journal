"""Daily job: retention cleanup, final vision pass, deterministic daily scaffold, LLM narrative refresh."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
from collections import Counter

from src.analysis.report_render import NARRATIVE_MARKER


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


def keep_existing_narrative(scaffold: str, existing: str) -> str:
    """Append the existing '## LLM narrative' section (with its input stamp) to a fresh scaffold."""
    if NARRATIVE_MARKER not in existing:
        return scaffold
    return scaffold.rstrip() + "\n\n" + existing[existing.index(NARRATIVE_MARKER):]


def run_period(args, period: str, date: str | None = None) -> int:
    return subprocess.run(
        [
            sys.executable, "-m", "src.analysis.synthesize_period",
            "--journal-root", str(args.journal_root), "--config", str(args.config),
            "--period", period, "--date", date or args.date,
        ],
        cwd=pathlib.Path(__file__).parents[2],
    ).returncode


def catch_up_dates(date: str, days: int) -> list[str]:
    """The given date plus the `days` calendar days before it, oldest last."""
    if days <= 0:
        return [date]
    parsed = dt.date.fromisoformat(date)
    return [(parsed - dt.timedelta(days=offset)).isoformat() for offset in range(days, -1, -1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument(
        "--catch-up-days",
        type=int,
        default=1,
        help="Also rebuild this many previous days (default 1); 0 disables catch-up.",
    )
    args = parser.parse_args()

    subprocess.run([sys.executable, "-m", "src.infra.retention", "--journal-root", str(args.journal_root), "--config", str(args.config)], cwd=pathlib.Path(__file__).parents[2])
    subprocess.run([sys.executable, "-m", "src.analysis.analyze_screenshots", "--journal-root", str(args.journal_root), "--config", str(args.config), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
    # Yesterday's last hour still gains screenshots after midnight, and their vision results are
    # filed under the day they belong to, so yesterday is rebuilt too. The input stamp makes an
    # unchanged report a no-op, so this only reaches the model for hours that really changed.
    for date in catch_up_dates(args.date, args.catch_up_days):
        run_period(args, "hourly", date)

    daily_path = args.journal_root / "daily" / f"{args.date}.md"
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    existing = daily_path.read_text(encoding="utf-8") if daily_path.exists() else ""
    daily_path.write_text(keep_existing_narrative(render_daily_scaffold(args.journal_root, args.date), existing), encoding="utf-8")

    subprocess.run([sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(args.journal_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
    daily_code = run_period(args, "daily")
    run_period(args, "weekly")
    for date in catch_up_dates(args.date, args.catch_up_days):
        if date == args.date:
            continue
        run_period(args, "daily", date)
        run_period(args, "weekly", date)

    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        vault_root = config.get("vaultRoot")
    except (OSError, json.JSONDecodeError):
        vault_root = None
    if vault_root:
        subprocess.run([sys.executable, "-m", "src.orchestration.sync_vault", "--journal-root", str(args.journal_root), "--vault-root", str(vault_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
        subprocess.run([sys.executable, "-m", "src.orchestration.sync_entities", "--journal-root", str(args.journal_root), "--config", str(args.config), "--vault-root", str(vault_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])

    print(str(daily_path))
    return daily_code


if __name__ == "__main__":
    raise SystemExit(main())
