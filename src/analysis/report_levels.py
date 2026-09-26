"""One prompt builder for the hourly, daily and weekly reports: same JSON shape, different depth."""

from __future__ import annotations

LEVELS = ("hourly", "daily", "weekly")
# Bump when the prompt or section layout changes so existing reports are rebuilt.
REPORT_FORMAT_VERSION = "2"

_SHAPE = """Return only valid JSON with this shape:
{{
  "summary": "one concise factual paragraph",
  "on_screen": ["concrete things that were visible on screen: applications, pages, dashboards, tickets, files, terminal commands, chat topics"],
  "timeline": [{{"time": "{time_hint}", "activity": "what was observed"}}],
  "patterns": ["useful observed patterns"]
}}"""

_RULES = """This is analysis only: describe and interpret what was observed; do not recommend actions or give advice. Report only what the sources show. Do not invent intent, people, conversations, or conclusions. Keep private message content summarized: never quote message text, and omit passwords, tokens and keys. Write plain human-readable text: local times, real application and page names, no identifiers."""

_LEVELS = {
    "hourly": {
        "unit": "one hour",
        "sources": "per-screenshot notes describing what was on screen, plus a list of the active windows for that hour",
        "time_hint": "HH:MM",
        "depth": "Be specific and fine-grained. List every distinct screen in on_screen with the visible application, page, panel, file, ticket, dashboard or command names and other concrete details. Follow the actual sequence in the timeline, noting when the screen changed.",
    },
    "daily": {
        "unit": "one day",
        "sources": "the hourly reports of that day",
        "time_hint": "HH:MM",
        "depth": "Group the day by task or application. on_screen lists the main things seen in each block of work, not every screen. The timeline has one entry per block of work. Say how many hours the sources cover if the day is incomplete.",
    },
    "weekly": {
        "unit": "one week",
        "sources": "the daily reports of that week",
        "time_hint": "weekday and date, e.g. Tue 2026-09-22",
        "depth": "Stay general. on_screen names only the few notable screens or themes of the week. The timeline holds only the week's most significant moments. Do not merge the daily reports into a log.",
    },
}


def build_prompt(level: str) -> str:
    spec = _LEVELS[level]
    return (
        f"You are writing a factual personal activity report covering {spec['unit']}. "
        f"Your sources are {spec['sources']}.\n"
        f"{_SHAPE.format(time_hint=spec['time_hint'])}\n"
        f"{spec['depth']}\n"
        f"{_RULES}"
    )
