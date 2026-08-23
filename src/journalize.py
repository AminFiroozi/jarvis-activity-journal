"""Deterministic Markdown rendering for activity sessions and evidence."""

from __future__ import annotations

from collections import Counter
import datetime as dt
from pathlib import Path
from typing import Any


def render_journal(title: str, events: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> str:
    lines = [f"# {title}", "", "## Activity sessions", ""]
    if not sessions:
        lines.append("No activity evidence was recorded for this period.")
    else:
        counts = Counter(session.get("classification", "unknown") for session in sessions)
        lines.append("Time allocation: " + ", ".join(f"{name} ({count})" for name, count in sorted(counts.items())) + ".")
        lines.append("")
        for session in sessions:
            classification = session.get("classification", "unknown")
            confidence = session.get("confidence", 0)
            start = session.get("startAt", "unknown")
            end = session.get("endAt", "unknown")
            lines.append(f"- **{classification}** — {start} to {end} (confidence: {confidence:.2f})")
            evidence = session.get("eventIds", [])
            if evidence:
                lines.append("  Evidence: " + ", ".join(f"`{event_id}`" for event_id in evidence))

    lines.extend(["", "## Evidence", ""])
    if not events:
        lines.append("No activity evidence was recorded for this period.")
    else:
        for event in events:
            event_id = event.get("id", "unknown")
            observed = event.get("observedAt", event.get("timestamp", "unknown"))
            kind = event.get("kind", event.get("source", "activity"))
            application = event.get("application", event.get("process", "unknown"))
            lines.append(f"- `{event_id}` — {observed} — {kind} — {application}")

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
