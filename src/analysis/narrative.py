"""Shared evidence primitives for LLM-narrative synthesis stages."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Callable

from src.analysis.sessionize import detect_sessions


def local_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        stamp = str(value)
        return stamp[11:16] if len(stamp) >= 16 else stamp
    return parsed.astimezone().strftime("%H:%M")


def event_stamp(event: dict) -> str | None:
    return event.get("localTimestamp") or event.get("timestamp")


def truncate(text: str, limit: int) -> str:
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def compact_event(event: dict) -> dict | None:
    source = event.get("source")
    if source == "foreground-window":
        exe = pathlib.Path(str(event.get("executable", ""))).stem or event.get("process", "")
        return {"t": local_time(event_stamp(event)), "type": "window", "app": exe, "title": truncate(event.get("windowTitle", ""), 60)}
    if source == "focused-content":
        return {"t": local_time(event_stamp(event)), "type": "content", "app": event.get("process", ""), "text": truncate(event.get("content", ""), 150)}
    if source == "screenshot-vision":
        analysis = event.get("analysis") or {}
        return {"t": local_time(event_stamp(event)), "type": "screen", "summary": truncate(analysis.get("summary", ""), 200), "apps": analysis.get("applications", []), "activity": analysis.get("activity_type", "")}
    return None


def compact_session(session: dict) -> dict:
    start = local_time(session.get("startAt"))
    end = local_time(session.get("endAt"))
    return {
        "t": f"{start}-{end}" if start and end else start or end,
        "class": session.get("classification", "unknown"),
        "apps": session.get("apps") or [],
    }


def parse_model_json(content: str) -> dict:
    cleaned = str(content).strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    value = json.loads(cleaned.strip())
    if not isinstance(value, dict):
        raise ValueError("Model response was not a JSON object")
    return value


def read_events(
    journal_root: pathlib.Path,
    date: str,
    compact: Callable[[dict], dict | None] = compact_event,
    limit: int = 60,
) -> dict:
    raw_events: list[dict] = []
    compacted: list[dict] = []
    for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
        path = journal_root / "raw" / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                raw_events.append(record)
                event = compact(record)
                if event:
                    compacted.append(event)
    sessions = [compact_session(session) for session in detect_sessions(raw_events)]
    return {"sessions": sessions, "recent": compacted[-limit:]}


def fit_evidence(sessions: list[dict], recent: list[dict], max_chars: int) -> tuple[list[dict], list[dict], str]:
    evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    while len(evidence) > max_chars and len(recent) > 5:
        recent = recent[len(recent) // 3:]
        evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    while len(evidence) > max_chars and len(sessions) > 5:
        sessions = sessions[len(sessions) // 5:]
        evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    return sessions, recent, evidence
