#!/usr/bin/env python3
"""Build deterministic hourly and weekly journal documents from local activity evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

from src.analysis.journalize import render_journal
from src.analysis.sessionize import detect_sessions


def read_day_events(journal_root: pathlib.Path, date: str) -> list[dict]:
    events: list[dict] = []
    for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
        path = journal_root / "raw" / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def event_hour(event: dict) -> int | None:
    value = event.get("localTimestamp") or event.get("timestamp")
    if not isinstance(value, str) or len(value) < 13:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).hour
    except ValueError:
        return None


def write_hourly(journal_root: pathlib.Path, date: str, events: list[dict]) -> list[pathlib.Path]:
    grouped: dict[int, list[dict]] = {}
    for event in events:
        hour = event_hour(event)
        if hour is not None:
            grouped.setdefault(hour, []).append(event)
    written = []
    for hour, hour_events in sorted(grouped.items()):
        sessions = detect_sessions(hour_events)
        path = journal_root / "hourly" / date / f"{hour:02d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_journal(f"Hourly journal — {date} {hour:02d}:00", hour_events, sessions), encoding="utf-8")
        written.append(path)
    return written


def write_weekly(journal_root: pathlib.Path, date: str) -> pathlib.Path:
    parsed = dt.date.fromisoformat(date)
    year, week, weekday = parsed.isocalendar()
    monday = parsed - dt.timedelta(days=weekday - 1)
    week_events: list[dict] = []
    day = monday
    while day <= parsed:
        week_events.extend(read_day_events(journal_root, day.isoformat()))
        day += dt.timedelta(days=1)
    sessions = detect_sessions(week_events)
    path = journal_root / "weekly" / f"{year}-W{week:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_journal(f"Weekly journal — {year}-W{week:02d}", week_events, sessions), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal_root = pathlib.Path(args.journal_root)
    events = read_day_events(journal_root, args.date)
    hourly_written = write_hourly(journal_root, args.date, events)
    weekly_written = write_weekly(journal_root, args.date)
    print(json.dumps({"hourly": [str(path) for path in hourly_written], "weekly": str(weekly_written)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
