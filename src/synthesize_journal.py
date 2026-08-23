#!/usr/bin/env python3
"""Use the configured vision-language model to turn activity events into a daily narrative."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request


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
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
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


def read_events(journal: pathlib.Path, date: str) -> list[dict]:
    events: list[dict] = []
    for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
        path = journal / "raw" / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events[-120:]


def call_model(endpoint: str, model: str, api_key: str | None, events: list[dict]) -> dict:
    evidence = json.dumps(events, ensure_ascii=False, separators=(",", ":"))
    body = {"model": model, "temperature": 0.2, "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"Observed events for the day:\n{evidence}"}]}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return parse_model_json(content)


def main() -> int:
    args = parse_args()
    journal = pathlib.Path(args.journal_root)
    events = read_events(journal, args.date)
    status_path = journal / "raw" / f"journal-{args.date}.status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if not events:
        status_path.write_text(json.dumps({"date": args.date, "status": "no-events"}) + "\n", encoding="utf-8")
        return 0
    try:
        narrative = call_model(args.endpoint, args.model, os.environ.get(args.api_key_env), events)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as error:
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
