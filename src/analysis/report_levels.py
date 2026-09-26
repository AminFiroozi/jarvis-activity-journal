"""One prompt builder for the hourly, daily and weekly reports: same JSON shape, different depth."""

from __future__ import annotations

LEVELS = ("hourly", "daily", "weekly")
# Bump when the prompt or section layout changes so existing reports are rebuilt.
REPORT_FORMAT_VERSION = "4"

_SHAPE = """Return only valid JSON with this shape:
{{
  "summary": "a factual analysis of the period, as long as the sources warrant (one or more paragraphs)",
  "timeline": [{{"time": "{time_hint}", "activity": "what was seen and done, with concrete names"}}],
  "patterns": ["useful observed patterns"]
}}"""

_RULES = """This is analysis only: describe and interpret what was observed; do not recommend actions or give advice. Report only what the sources show. Do not invent intent, people, conversations, or conclusions. Keep private message content summarized: never quote message text, and omit passwords, tokens and keys. For chat conversations keep the correspondent, the topic and the specific points discussed (questions, requests, decisions, deadlines, numbers, ticket IDs, file names), still never quoting message text. Write plain human-readable text: local times, real application and page names, no identifiers."""

_LEVELS = {
    "hourly": {
        "unit": "one hour",
        "sources": "per-screenshot notes describing what was on screen, plus a list of the active windows for that hour",
        "time_hint": "HH:MM",
        "depth": "Be thorough and specific: this report may be long. The timeline follows the actual sequence of the hour in detail — for each change of screen say what was open (application, page, dashboard, ticket, file, command, chat topic) and what the person appeared to be doing. Prefer concrete names over generalities.",
    },
    "daily": {
        "unit": "one day",
        "sources": "the hourly reports of that day",
        "time_hint": "HH:MM",
        "depth": "Write a full analysis of the day, longer and richer than an hourly report. The summary may run to several paragraphs. The timeline has one detailed entry per block of work, naming the concrete applications, pages, tickets and files involved. Patterns cover how the day was spent. Say how many hours the sources cover if the day is incomplete.",
    },
    "weekly": {
        "unit": "one week",
        "sources": "the daily reports of that week",
        "time_hint": "weekday and date, e.g. Tue 2026-09-22",
        "depth": "Write a full analysis of the week, longer than a daily report. The summary may run to several paragraphs covering the week's themes. The timeline holds the week's significant moments by day. Patterns cover how the week was spent across days.",
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
