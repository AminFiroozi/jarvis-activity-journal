#!/usr/bin/env python3
"""Synthesize hourly and weekly narrative journals from local activity evidence."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
from typing import Callable

from src.analysis.narrative import compact_event, compact_session, event_stamp, fit_evidence, parse_model_json
from src.analysis.sessionize import detect_sessions
from src.providers.model_client import call_chat_completions


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
