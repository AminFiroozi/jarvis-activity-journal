#!/usr/bin/env python3
"""Synthesize hourly and weekly narrative journals from local activity evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
from typing import Callable

from src.analysis.narrative import compact_event, compact_session, event_stamp, fit_evidence, parse_model_json
from src.analysis.sessionize import detect_sessions
from src.infra.heartbeat import write_heartbeat
from src.infra.processing_queue import FileJobQueue
from src.providers.model_client import ProviderError, call_chat_completions, resolve_provider


HOURLY_PROMPT = """You are writing a factual, detailed personal activity journal entry for ONE HOUR of observed computer events.
Return only valid JSON with this shape:
{
  "summary": "one or two concise factual sentences describing this hour",
  "timeline": [{"time": "HH:MM", "activity": "what was observed"}],
  "patterns": ["useful observed patterns within this hour"],
  "next_actions": ["reasonable next actions grounded in evidence, if any"],
  "confidence": 0.0
}
Be specific and fine-grained — this is a single hour, so capture the actual sequence of what happened, not a vague summary. Do not invent intent, accomplishments, people, conversations, or conclusions. Mark uncertain interpretations through a lower confidence value. Keep private message content summarized rather than reproduced."""

WEEKLY_PROMPT = """You are writing a factual, general personal activity journal entry summarizing ONE WEEK of observed computer events.
Return only valid JSON with this shape:
{
  "summary": "one concise factual paragraph covering the week as a whole",
  "timeline": [{"time": "HH:MM", "activity": "a few of the week's most significant moments only, not an hour-by-hour recap"}],
  "patterns": ["broad patterns observed across the week"],
  "next_actions": ["reasonable next actions grounded in evidence, if any"],
  "confidence": 0.0
}
Stay general — cover fewer, broader points rather than every detail; this is a week-level summary, not a merged hourly log. Do not invent intent, accomplishments, people, conversations, or conclusions. Mark uncertain interpretations through a lower confidence value. Keep private message content summarized rather than reproduced."""

_SCREENSHOT_FILENAME_PATTERN = re.compile(r"^screen-(\d{2})-\d{2}-\d{2}-\d+\.jpg$")


def _event_hour(event: dict) -> int | None:
    value = event_stamp(event)
    if not isinstance(value, str) or len(value) < 13:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).hour
    except ValueError:
        return None


def read_period_events(
    journal_root: pathlib.Path,
    dates: list[str],
    hour: int | None = None,
    compact: Callable[[dict], dict | None] = compact_event,
    limit: int = 1000,
) -> dict:
    raw_events: list[dict] = []
    compacted: list[dict] = []
    for date in dates:
        for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
            path = journal_root / "raw" / filename
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if hour is not None and _event_hour(record) != hour:
                    continue
                raw_events.append(record)
                event = compact(record)
                if event:
                    compacted.append(event)
    sessions = [compact_session(session) for session in detect_sessions(raw_events)]
    return {"sessions": sessions, "recent": compacted[-limit:]}


def has_evidence_for_hour(journal_root: pathlib.Path, date: str, hour: int) -> bool:
    for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
        path = journal_root / "raw" / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _event_hour(record) == hour:
                return True
    screenshot_dir = journal_root / "screenshots" / date
    if screenshot_dir.exists():
        for path in screenshot_dir.glob("screen-*.jpg"):
            match = _SCREENSHOT_FILENAME_PATTERN.match(path.name)
            if match and int(match.group(1)) == hour:
                return True
    return False


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


def render_period_document(title: str, narrative: dict) -> str:
    summary = str(narrative.get("summary", "No narrative summary returned.")).strip()
    lines = [f"# {title}", "", summary, ""]
    for section_title, key in (("Timeline", "timeline"), ("Patterns", "patterns"), ("Next actions", "next_actions")):
        values = narrative.get(key) or []
        if not values:
            continue
        lines.extend([f"### {section_title}", ""])
        for value in values:
            if isinstance(value, dict):
                lines.append(f"- {value.get('time', '')} — {value.get('activity', '')}".strip(" —"))
            else:
                lines.append(f"- {value}")
        lines.append("")
    lines.append(f"_LLM confidence: {narrative.get('confidence', 'unknown')}_")
    return "\n".join(lines).rstrip() + "\n"


def call_model(provider: dict, evidence_dict: dict, prompt: str, max_chars: int = 6000) -> dict:
    sessions, recent, evidence = fit_evidence(evidence_dict["sessions"], evidence_dict["recent"], max_chars)
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": f"Observed events:\n{evidence}"}]
    content = call_chat_completions(provider, messages, temperature=0.2)
    return parse_model_json(content)


def synthesize_hour(provider: dict, journal_root: pathlib.Path, date: str, hour: int) -> dict:
    evidence = read_period_events(journal_root, [date], hour=hour)
    narrative = call_model(provider, evidence, HOURLY_PROMPT)
    path = journal_root / "hourly" / date / f"{hour:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_period_document(f"Hourly journal — {date} {hour:02d}:00", narrative), encoding="utf-8")
    return {"path": str(path)}


def synthesize_week(provider: dict, journal_root: pathlib.Path, date: str) -> dict:
    year, week, dates = week_dates(date)
    evidence = read_period_events(journal_root, dates)
    narrative = call_model(provider, evidence, WEEKLY_PROMPT)
    path = journal_root / "weekly" / f"{year}-W{week:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_period_document(f"Weekly journal — {year}-W{week:02d}", narrative), encoding="utf-8")
    return {"path": str(path), "year": year, "week": week}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--period", required=True, choices=("hourly", "weekly"))
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal = args.journal_root
    config = json.loads(args.config.read_text(encoding="utf-8"))
    stage_key = "hourlySynthesis" if args.period == "hourly" else "weeklySynthesis"
    stage_config = config.get(stage_key) or {}
    heartbeat_name = f"{args.period}-synthesis"

    if not stage_config.get("enabled", True):
        print(json.dumps({"period": args.period, "status": "disabled"}))
        return 0

    try:
        provider = resolve_provider(config, stage_key)
    except ProviderError as error:
        write_heartbeat(journal, heartbeat_name, "failed", error_message=str(error))
        print(f"{args.period} synthesis failed: {error}")
        return 0

    max_attempts = int(stage_config.get("maxAttempts", 5))
    retry_delay_seconds = int(stage_config.get("retryDelaySeconds", 60))
    queue = FileJobQueue(journal / "queue-period")

    results: list[dict] = []
    attempted: set[str] = set()
    while True:
        job = queue.claim(kind=args.period, exclude_ids=attempted)
        if job is None:
            break
        attempted.add(job["id"])
        payload = job["payload"]
        try:
            if args.period == "hourly":
                result = synthesize_hour(provider, journal, payload["date"], payload["hour"])
            else:
                result = synthesize_week(provider, journal, payload["date"])
            queue.complete(job["id"], result)
            results.append({"status": "complete", **result})
        except (OSError, ValueError, KeyError, json.JSONDecodeError, ProviderError) as error:
            outcome = queue.fail(job["id"], str(error), max_attempts=max_attempts, retry_delay_seconds=retry_delay_seconds)
            results.append({"status": outcome["status"], "error": str(error)})

    if args.period == "hourly":
        now = dt.datetime.now()
        hour = now.hour
        job_id = f"hourly-{args.date}-{hour:02d}"
        if queue.find(job_id) is None:
            if not has_evidence_for_hour(journal, args.date, hour):
                results.append({"status": "no-evidence", "date": args.date, "hour": hour})
            else:
                try:
                    result = synthesize_hour(provider, journal, args.date, hour)
                    results.append({"status": "complete", **result})
                except (OSError, ValueError, KeyError, json.JSONDecodeError, ProviderError) as error:
                    queue.enqueue("hourly", {"date": args.date, "hour": hour}, job_id=job_id)
                    results.append({"status": "failed", "error": str(error)})
    else:
        year, week, _ = week_dates(args.date)
        job_id = f"weekly-{year}-W{week:02d}"
        if queue.find(job_id) is None:
            try:
                result = synthesize_week(provider, journal, args.date)
                results.append({"status": "complete", **result})
            except (OSError, ValueError, KeyError, json.JSONDecodeError, ProviderError) as error:
                queue.enqueue("weekly", {"date": args.date}, job_id=job_id)
                results.append({"status": "failed", "error": str(error)})

    print(json.dumps({"period": args.period, "results": results}, ensure_ascii=False))
    failed = [item for item in results if item["status"] == "failed"]
    completed = [item for item in results if item["status"] == "complete"]
    if failed:
        write_heartbeat(journal, heartbeat_name, "failed", items_processed=len(completed), error_message=failed[-1]["error"])
    else:
        write_heartbeat(journal, heartbeat_name, "success", items_processed=len(completed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
