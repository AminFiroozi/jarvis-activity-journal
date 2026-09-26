#!/usr/bin/env python3
"""Build hourly, daily and weekly reports; each level compacts the Markdown of the level below."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib

from src.analysis.narrative import parse_model_json, truncate
from src.analysis.report_levels import LEVELS, build_prompt
from src.analysis.report_render import (
    daily_narrative_text,
    read_input_stamp,
    render_report,
    strip_input_stamp,
    upsert_daily_narrative,
    with_input_stamp,
)
from src.infra.heartbeat import write_heartbeat
from src.providers.model_client import ProviderError, call_chat_completions, resolve_provider

STAGE_KEYS = {"hourly": "hourlySynthesis", "daily": "journalSynthesis", "weekly": "weeklySynthesis"}
MAX_INPUT_CHARS = {"hourly": 24000, "daily": 16000, "weekly": 16000}
MAX_ACTIVITY_LINES = 40
_REPEAT_MARKER = "\nUnchanged since "


def week_dates(date: str) -> tuple[int, int, list[str]]:
    parsed = dt.date.fromisoformat(date)
    year, week, weekday = parsed.isocalendar()
    monday = parsed - dt.timedelta(days=weekday - 1)
    dates = []
    day = monday
    while day <= parsed:
        dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    return year, week, dates


def _activity_records(journal_root: pathlib.Path, date: str):
    path = journal_root / "raw" / f"activity-{date}.jsonl"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        stamp = record.get("localTimestamp")
        if record.get("source") != "foreground-window" or not record.get("process") or not isinstance(stamp, str) or len(stamp) < 16:
            continue
        if stamp[:10] != date or not stamp[11:13].isdigit():
            continue
        yield record, int(stamp[11:13]), stamp[11:16]


def activity_lines(journal_root: pathlib.Path, date: str, hour: int) -> list[str]:
    runs: list[list[str]] = []
    for record, record_hour, clock in _activity_records(journal_root, date):
        if record_hour != hour:
            continue
        app = pathlib.Path(str(record.get("executable") or "")).stem or str(record["process"])
        title = truncate(record.get("windowTitle") or "", 60)
        if runs and runs[-1][2] == app and runs[-1][3] == title:
            runs[-1][1] = clock
        else:
            runs.append([clock, clock, app, title])
    lines = [
        f"{start if start == end else f'{start}–{end}'} {app}" + (f" — {title}" if title else "")
        for start, end, app, title in runs
    ]
    if len(lines) > MAX_ACTIVITY_LINES:
        step = -(-len(lines) // MAX_ACTIVITY_LINES)
        lines = lines[::step]
    return lines


def _screen_dir(journal_root: pathlib.Path, date: str, hour: int) -> pathlib.Path:
    return journal_root / "screens" / date / f"{hour:02d}"


def hours_with_input(journal_root: pathlib.Path, date: str) -> list[int]:
    hours: set[int] = set()
    screens = journal_root / "screens" / date
    if screens.exists():
        for directory in screens.iterdir():
            if directory.is_dir() and directory.name.isdigit() and any(directory.glob("*.md")):
                hours.add(int(directory.name))
    for _, record_hour, _ in _activity_records(journal_root, date):
        hours.add(record_hour)
    return sorted(hours)


def _fit(parts: list[str], limit: int) -> list[str]:
    while len(parts) > 2 and len("\n\n".join(parts)) > limit:
        parts = parts[::2]
    return parts


def gather_hour(journal_root: pathlib.Path, date: str, hour: int) -> str | None:
    directory = _screen_dir(journal_root, date, hour)
    files = sorted(directory.glob("*.md")) if directory.exists() else []
    activity = activity_lines(journal_root, date, hour)
    if not files and not activity:
        return None
    screens: list[str] = []
    repeats = 0
    for file in files:
        text = strip_input_stamp(file.read_text(encoding="utf-8")).strip()
        if _REPEAT_MARKER in text:
            repeats += 1
        else:
            screens.append(text)
    header = f"Hour {hour:02d}:00 on {date}."
    activity_block = "## Active windows\n\n" + "\n".join(f"- {line}" for line in activity) if activity else ""
    budget = MAX_INPUT_CHARS["hourly"] - len(activity_block)
    parts = [header, f"## Screens ({len(screens)} analysed)"] + _fit(screens, budget)
    if repeats:
        parts.append(f"{repeats} further screenshot(s) were unchanged repeats of the screens above.")
    if activity_block:
        parts.append(activity_block)
    return "\n\n".join(parts)


def gather_day(journal_root: pathlib.Path, date: str) -> str | None:
    directory = journal_root / "hourly" / date
    files = sorted(directory.glob("*.md")) if directory.exists() else []
    parts = [strip_input_stamp(file.read_text(encoding="utf-8")).strip() for file in files]
    parts = [part for part in parts if part]
    if not parts:
        return None
    return "\n\n".join([f"Day {date}, {len(parts)} hourly report(s)."] + _fit(parts, MAX_INPUT_CHARS["daily"]))


def gather_week(journal_root: pathlib.Path, date: str) -> str | None:
    _, _, dates = week_dates(date)
    parts: list[str] = []
    for day in dates:
        path = journal_root / "daily" / f"{day}.md"
        if not path.exists():
            continue
        narrative = daily_narrative_text(path.read_text(encoding="utf-8"))
        if narrative:
            label = dt.date.fromisoformat(day).strftime("%a %Y-%m-%d")
            parts.append(f"## {label}\n\n{narrative}")
    if not parts:
        return None
    return "\n\n".join([f"Week up to {date}, {len(parts)} daily report(s)."] + _fit(parts, MAX_INPUT_CHARS["weekly"]))


def call_report_model(provider: dict, level: str, source_text: str) -> dict:
    messages = [
        {"role": "system", "content": build_prompt(level)},
        {"role": "user", "content": f"Sources:\n{source_text}"},
    ]
    last_error: Exception | None = None
    for _ in range(2):
        content = call_chat_completions(provider, messages, temperature=0.2)
        try:
            return parse_model_json(content)
        except ValueError as error:
            last_error = error
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "That was not valid JSON. Return only the corrected JSON object."},
            ]
    raise ValueError(f"model returned invalid JSON twice: {last_error}")


def build_report(provider: dict, journal_root: pathlib.Path, level: str, date: str, hour: int | None = None) -> dict:
    if level == "hourly":
        source = gather_hour(journal_root, date, hour)
        path = journal_root / "hourly" / date / f"{hour:02d}.md"
        title = f"Hourly journal — {date} {hour:02d}:00"
    elif level == "daily":
        source = gather_day(journal_root, date)
        path = journal_root / "daily" / f"{date}.md"
        title = f"Automatic Activity Journal — {date}"
    else:
        source = gather_week(journal_root, date)
        year, week, _ = week_dates(date)
        path = journal_root / "weekly" / f"{year}-W{week:02d}.md"
        title = f"Weekly journal — {year}-W{week:02d}"
    if source is None:
        return {"status": "no-input"}
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if read_input_stamp(existing) == digest:
        return {"status": "unchanged", "path": str(path)}
    narrative = call_report_model(provider, level, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    if level == "daily":
        text = upsert_daily_narrative(existing or f"# {title}\n", narrative)
    else:
        text = render_report(title, narrative)
    path.write_text(with_input_stamp(text, digest), encoding="utf-8")
    return {"status": "complete", "path": str(path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--period", required=True, choices=LEVELS)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal = args.journal_root
    level = args.period
    heartbeat_name = f"{level}-synthesis"
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"{level} synthesis failed: {error}")
        return 1
    stage_key = STAGE_KEYS[level]
    if not (config.get(stage_key) or {}).get("enabled", True):
        print(json.dumps({"period": level, "status": "disabled"}))
        return 0
    try:
        provider = resolve_provider(config, stage_key)
    except (ProviderError, KeyError) as error:
        write_heartbeat(journal, heartbeat_name, "failed", error_message=str(error))
        print(f"{level} synthesis failed: {error}")
        return 1

    hours: list[int | None] = hours_with_input(journal, args.date) if level == "hourly" else [None]
    results: list[dict] = []
    for hour in hours:
        try:
            result = build_report(provider, journal, level, args.date, hour=hour)
        except (OSError, ValueError, KeyError, ProviderError) as error:
            result = {"status": "failed", "error": str(error)}
        if hour is not None:
            result["hour"] = hour
        results.append(result)

    print(json.dumps({"period": level, "results": results}, ensure_ascii=False))
    failed = [item for item in results if item["status"] == "failed"]
    completed = [item for item in results if item["status"] == "complete"]
    if failed:
        write_heartbeat(journal, heartbeat_name, "failed", items_processed=len(completed), error_message=failed[-1]["error"])
        return 1
    write_heartbeat(journal, heartbeat_name, "success", items_processed=len(completed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
