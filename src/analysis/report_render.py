"""Single Markdown renderer for the hourly, daily and weekly reports."""

from __future__ import annotations

import re

NARRATIVE_MARKER = "## LLM narrative"
SECTIONS = (("On screen", "on_screen"), ("Timeline", "timeline"), ("Patterns", "patterns"), ("Next actions", "next_actions"))
_STAMP = re.compile(r"\s*<!-- input: ([0-9a-f]+) -->\s*")


def _items(value) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        return []
    items = []
    for entry in value:
        if isinstance(entry, dict):
            text = f"{entry.get('time', '')} — {entry.get('activity', '')}".strip(" —")
        else:
            text = str(entry).strip()
        if text:
            items.append(text)
    return items


def render_sections(narrative: dict) -> str:
    summary = str(narrative.get("summary") or "No summary returned.").strip()
    lines = [summary, ""]
    for title, key in SECTIONS:
        items = _items(narrative.get(key))
        if not items:
            continue
        lines.extend([f"### {title}", ""])
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_report(title: str, narrative: dict) -> str:
    return f"# {title}\n\n{render_sections(narrative)}"


def read_input_stamp(text: str) -> str | None:
    match = _STAMP.search(text)
    return match.group(1) if match else None


def strip_input_stamp(text: str) -> str:
    if not text.strip():
        return ""
    return _STAMP.sub("\n", text).strip() + "\n"


def with_input_stamp(text: str, digest: str) -> str:
    return strip_input_stamp(text).rstrip("\n") + f"\n\n<!-- input: {digest} -->\n"


def upsert_daily_narrative(markdown: str, narrative: dict) -> str:
    markdown = strip_input_stamp(markdown)
    before = markdown.split(NARRATIVE_MARKER, 1)[0].rstrip() if NARRATIVE_MARKER in markdown else markdown.rstrip()
    return f"{before}\n\n{NARRATIVE_MARKER}\n\n{render_sections(narrative)}"


def daily_narrative_text(markdown: str) -> str | None:
    if NARRATIVE_MARKER not in markdown:
        return None
    body = strip_input_stamp(markdown.split(NARRATIVE_MARKER, 1)[1]).strip()
    return body or None
