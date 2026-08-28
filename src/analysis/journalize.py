"""Deterministic Markdown rendering for activity sessions and evidence."""

from __future__ import annotations

from collections import Counter
import datetime as dt
from pathlib import Path
from typing import Any


_KIND_LABELS = {"foreground-window": "window", "focused-content": "content", "screenshot-vision": "screen", "git-project": "project"}


def _local_time(value: str | None, fmt: str = "%H:%M") -> str:
    if not value:
        return "?"
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.astimezone().strftime(fmt)


def _duration_label(start: str | None, end: str | None) -> str:
    try:
        start_dt = dt.datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_dt = dt.datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    minutes = max(0, round((end_dt - start_dt).total_seconds() / 60))
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes}m"
    hours, remainder = divmod(minutes, 60)
    return f"{hours}h{remainder:02d}m" if remainder else f"{hours}h"


def _event_kind_and_app(event: dict[str, Any]) -> tuple[str, str]:
    kind = event.get("kind") or event.get("source") or "activity"
    application = event.get("application") or event.get("process")
    if not application and kind == "screenshot-vision":
        applications = (event.get("analysis") or {}).get("applications")
        if isinstance(applications, list) and applications:
            application = ", ".join(str(item) for item in applications)
        elif isinstance(applications, str) and applications:
            application = applications
    return _KIND_LABELS.get(kind, kind), application or "unknown"


def _event_time(event: dict[str, Any]) -> str | None:
    return event.get("observedAt") or event.get("timestamp")


def _render_evidence(events: list[dict[str, Any]]) -> list[str]:
    lines = []
    index = 0
    while index < len(events):
        signature = _event_kind_and_app(events[index])
        start_time = _event_time(events[index])
        run_end = index
        while run_end + 1 < len(events) and _event_kind_and_app(events[run_end + 1]) == signature:
            run_end += 1
        end_time = _event_time(events[run_end])
        count = run_end - index + 1
        kind_label, application = signature
        time_label = _local_time(start_time) if count == 1 or start_time == end_time else f"{_local_time(start_time)}–{_local_time(end_time)}"
        suffix = "" if count == 1 else f" ({count} samples)"
        lines.append(f"- {time_label} — {kind_label} — {application}{suffix}")
        index = run_end + 1
    return lines


def render_journal(title: str, events: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> str:
    lines = [f"# {title}", "", "## Activity sessions", ""]
    if not sessions:
        lines.append("No activity evidence was recorded for this period.")
    else:
        counts = Counter(session.get("classification", "unknown") for session in sessions)
        lines.append("Time allocation: " + ", ".join(f"{name} ({count} session{'s' if count != 1 else ''})" for name, count in sorted(counts.items())) + ".")
        lines.append("")
        for session in sessions:
            classification = session.get("classification", "unknown")
            start = session.get("startAt")
            end = session.get("endAt")
            apps = session.get("apps") or []
            duration = _duration_label(start, end)
            time_range = f"{_local_time(start)}–{_local_time(end)}"
            detail = f" ({duration})" if duration else ""
            apps_label = f" — {', '.join(apps)}" if apps else ""
            lines.append(f"- {time_range}{detail} — {classification}{apps_label}")

    lines.extend(["", "## Evidence", ""])
    if not events:
        lines.append("No activity evidence was recorded for this period.")
    else:
        lines.extend(_render_evidence(events))

    return "\n".join(lines).rstrip() + "\n"


def _parse_time(event: dict[str, Any]) -> dt.datetime:
    value = event.get("observedAt", event.get("timestamp"))
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def write_journal_documents(
    journal_root: Path,
    date: str,
    events: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> list[Path]:
    """Write deterministic hourly, daily, and ISO-weekly Markdown documents."""
    root = Path(journal_root)
    written: list[Path] = []
    daily = root / "daily" / f"{date}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(render_journal(f"Daily journal — {date}", events, sessions), encoding="utf-8")
    written.append(daily)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(_parse_time(event).hour, []).append(event)
    for hour, hour_events in sorted(grouped.items()):
        path = root / "hourly" / date / f"{hour:02d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_journal(f"Hourly journal — {date} {hour:02d}:00", hour_events, []), encoding="utf-8")
        written.append(path)

    parsed_date = dt.date.fromisoformat(date)
    year, week, _ = parsed_date.isocalendar()
    weekly = root / "weekly" / f"{year}-W{week:02d}.md"
    weekly.parent.mkdir(parents=True, exist_ok=True)
    weekly.write_text(render_journal(f"Weekly journal — {year}-W{week:02d}", events, sessions), encoding="utf-8")
    written.append(weekly)
    return written
