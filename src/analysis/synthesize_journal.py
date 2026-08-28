#!/usr/bin/env python3
"""Use the configured vision-language model to turn activity events into a daily narrative."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

from src.analysis.sessionize import detect_sessions
from src.providers.model_client import ProviderError, call_chat_completions, resolve_provider


PROMPT = """You are writing a factual personal activity journal from observed computer events.
Return only valid JSON with this shape:
{
  "summary": "one concise factual paragraph",
  "accomplishments": ["observed completed actions"],
  "timeline": [{"time": "HH:MM", "activity": "what was observed"}],
  "patterns": ["useful observed patterns"],
  "blockers": ["observed blockers, otherwise empty"],
  "next_actions": ["reasonable next actions grounded in evidence"],
  "confidence": 0.0
}
Do not invent intent, accomplishments, people, conversations, or conclusions. Mark uncertain interpretations through a lower confidence value. Keep private message content summarized rather than reproduced."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


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


def upsert_narrative(markdown: str, narrative: dict) -> str:
    marker = "## LLM narrative"
    summary = str(narrative.get("summary", "No narrative summary returned.")).strip()
    lines = [marker, "", summary, ""]
    for title, key in (("Accomplishments", "accomplishments"), ("Timeline", "timeline"), ("Patterns", "patterns"), ("Blockers", "blockers"), ("Next actions", "next_actions")):
        values = narrative.get(key) or []
        if not values:
            continue
        lines.extend([f"### {title}", ""])
        for value in values:
            if isinstance(value, dict):
                lines.append(f"- {value.get('time', '')} — {value.get('activity', '')}".strip(" —"))
            else:
                lines.append(f"- {value}")
        lines.append("")
    lines.append(f"_LLM confidence: {narrative.get('confidence', 'unknown')}_")
    section = "\n".join(lines).rstrip() + "\n"
    if marker in markdown:
        before = markdown.split(marker, 1)[0].rstrip()
        return before + "\n\n" + section
    return markdown.rstrip() + "\n\n" + section


def local_time(event: dict) -> str:
    stamp = event.get("localTimestamp") or event.get("timestamp") or ""
    return stamp[11:16] if len(stamp) >= 16 else stamp


def truncate(text: str, limit: int) -> str:
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def compact_event(event: dict) -> dict | None:
    source = event.get("source")
    if source == "foreground-window":
        exe = pathlib.Path(str(event.get("executable", ""))).stem or event.get("process", "")
        return {"t": local_time(event), "type": "window", "app": exe, "title": truncate(event.get("windowTitle", ""), 60)}
    if source == "focused-content":
        return {"t": local_time(event), "type": "content", "app": event.get("process", ""), "text": truncate(event.get("content", ""), 150)}
    if source == "screenshot-vision":
        analysis = event.get("analysis") or {}
        return {"t": local_time(event), "type": "screen", "summary": truncate(analysis.get("summary", ""), 200), "apps": analysis.get("applications", []), "activity": analysis.get("activity_type", "")}
    return None


def compact_session(session: dict) -> dict:
    start = _session_local_time(session.get("startAt"))
    end = _session_local_time(session.get("endAt"))
    return {
        "t": f"{start}-{end}" if start and end else start or end,
        "class": session.get("classification", "unknown"),
        "apps": session.get("apps") or [],
    }


def _session_local_time(iso_utc: str | None) -> str:
    if not iso_utc:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(iso_utc)
    except ValueError:
        return iso_utc[11:16] if len(iso_utc) >= 16 else iso_utc
    return parsed.astimezone().strftime("%H:%M")


def read_events(journal: pathlib.Path, date: str) -> dict:
    raw_events: list[dict] = []
    compacted: list[dict] = []
    for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
        path = journal / "raw" / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                raw_events.append(record)
                event = compact_event(record)
                if event:
                    compacted.append(event)
    sessions = [compact_session(session) for session in detect_sessions(raw_events)]
    return {"sessions": sessions, "recent": compacted[-60:]}


def call_model(provider: dict, evidence_dict: dict) -> dict:
    sessions = evidence_dict["sessions"]
    recent = evidence_dict["recent"]
    evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    max_chars = 6000
    while len(evidence) > max_chars and len(recent) > 5:
        recent = recent[len(recent) // 3:]
        evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    while len(evidence) > max_chars and len(sessions) > 5:
        sessions = sessions[len(sessions) // 5:]
        evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"Observed events for the day:\n{evidence}"}]
    content = call_chat_completions(provider, messages, temperature=0.2)
    return parse_model_json(content)


def main() -> int:
    args = parse_args()
    journal = pathlib.Path(args.journal_root)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    evidence_dict = read_events(journal, args.date)
    status_path = journal / "raw" / f"journal-{args.date}.status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if not evidence_dict["sessions"] and not evidence_dict["recent"]:
        status_path.write_text(json.dumps({"date": args.date, "status": "no-events"}) + "\n", encoding="utf-8")
        return 0
    try:
        provider = resolve_provider(config, "journalSynthesis")
        narrative = call_model(provider, evidence_dict)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ProviderError) as error:
        status_path.write_text(json.dumps({"date": args.date, "status": "failed", "error": str(error)}) + "\n", encoding="utf-8")
        print(f"Journal synthesis failed: {error}")
        return 1
    raw_path = journal / "raw" / f"journal-{args.date}.json"
    raw_path.write_text(json.dumps(narrative, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    daily_path = journal / "daily" / f"{args.date}.md"
    markdown = daily_path.read_text(encoding="utf-8") if daily_path.exists() else f"# Automatic Activity Journal — {args.date}\n"
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.write_text(upsert_narrative(markdown, narrative), encoding="utf-8")
    status_path.write_text(json.dumps({"date": args.date, "status": "complete", "daily": str(daily_path)}) + "\n", encoding="utf-8")
    print(str(daily_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
