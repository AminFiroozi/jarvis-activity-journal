#!/usr/bin/env python3
"""Use the configured vision-language model to turn activity events into a daily narrative."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

from src.analysis.narrative import compact_event, compact_session, fit_evidence, local_time, parse_model_json, read_events, truncate
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


def call_model(provider: dict, evidence_dict: dict) -> dict:
    sessions, recent, evidence = fit_evidence(evidence_dict["sessions"], evidence_dict["recent"], max_chars=6000)
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
