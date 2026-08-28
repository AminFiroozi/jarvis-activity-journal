"""Detect contiguous activity sessions from JSONL event dictionaries."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable


MAX_GAP_SECONDS = 15 * 60
CLASSIFICATIONS = {"coding", "browsing", "communication", "terminal", "meeting", "idle", "mixed"}

_APPLICATION_CLASSES = {
    "coding": ("code", "cursor", "pycharm", "intellij", "webstorm", "visual studio", "xcode", "sublime", "vim", "emacs"),
    "browsing": ("chrome", "firefox", "edge", "safari", "browser", "brave", "opera"),
    "communication": ("slack", "telegram", "discord", "signal", "whatsapp", "messenger", "outlook", "mail", "chat"),
    "terminal": ("terminal", "powershell", "cmd", "command prompt", "bash", "zsh", "console", "conhost", "windows terminal"),
    "meeting": ("zoom", "meet", "webex", "teams meeting", "meeting"),
}
_ACTIVITY_CLASSES = {
    "coding": {"coding", "development", "programming", "editing"},
    "browsing": {"browsing", "research", "web"},
    "communication": {"communication", "communicating", "chatting", "chat", "email"},
    "terminal": {"terminal", "command-line", "command_line", "shell"},
    "meeting": {"meeting", "video-call", "video_call", "conference"},
    "idle": {"idle", "away"},
}


def detect_sessions(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deterministic activity sessions for JSONL-style event dictionaries."""
    prepared = []
    for position, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            continue
        timestamp = _event_time(event)
        if timestamp is None:
            continue
        prepared.append((_to_utc(timestamp), position, event))

    prepared.sort(key=lambda item: (item[0], item[1]))
    sessions: list[dict[str, Any]] = []
    current: list[tuple[datetime, int, dict[str, Any]]] = []

    for item in prepared:
        if not current or _compatible(current[-1], item):
            current.append(item)
        else:
            sessions.append(_build_session(len(sessions) + 1, current))
            current = [item]
    if current:
        sessions.append(_build_session(len(sessions) + 1, current))
    return sessions


def sessionize(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility alias for callers that use the roadmap's module name as a verb."""
    return detect_sessions(events)


def _event_time(event: dict[str, Any]) -> datetime | None:
    for key in ("observedAt", "timestamp", "localTimestamp"):
        value = event.get(key)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(event: dict[str, Any]) -> str:
    values = []
    for key in ("activity_type", "activityType", "kind", "source", "application", "applicationName", "process", "windowTitle"):
        value = event.get(key)
        if isinstance(value, str):
            values.append(value.casefold())
    analysis = event.get("analysis")
    if isinstance(analysis, dict):
        for key in ("activity_type", "activityType", "summary"):
            value = analysis.get(key)
            if isinstance(value, str):
                values.append(value.casefold())
        for key in ("applications", "projects"):
            value = analysis.get(key)
            if isinstance(value, list):
                values.extend(str(item).casefold() for item in value if isinstance(item, str))
    return " ".join(values)


def _project(event: dict[str, Any]) -> str | None:
    for key in ("project", "projectPath", "repository", "repositoryPath"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    return None


def _application(event: dict[str, Any]) -> str:
    for key in ("application", "applicationName", "process", "executable"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.casefold()
    return ""


def _application_display_name(event: dict[str, Any]) -> str:
    for key in ("application", "applicationName", "process", "executable"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_idle(event: dict[str, Any]) -> bool:
    if event.get("active") is False or event.get("idle") is True:
        return True
    idle_seconds = event.get("idleSeconds")
    if isinstance(idle_seconds, (int, float)) and idle_seconds >= 300:
        return True
    return any(value in _text(event).split() for value in _ACTIVITY_CLASSES["idle"])


def _class_evidence(event: dict[str, Any]) -> set[str]:
    if _is_idle(event):
        return {"idle"}
    text = _text(event)
    found = set()
    for label, values in _ACTIVITY_CLASSES.items():
        if any(value in text for value in values):
            found.add(label)
    app = _application(event)
    for label, values in _APPLICATION_CLASSES.items():
        if any(value in app for value in values):
            found.add(label)
    return found


def _compatible(previous: tuple[datetime, int, dict[str, Any]], current: tuple[datetime, int, dict[str, Any]]) -> bool:
    previous_time, _, previous_event = previous
    current_time, _, current_event = current
    if (current_time - previous_time).total_seconds() >= MAX_GAP_SECONDS:
        return False
    previous_idle, current_idle = _is_idle(previous_event), _is_idle(current_event)
    if previous_idle and current_idle:
        return True
    if previous_idle or current_idle:
        return False
    previous_project, current_project = _project(previous_event), _project(current_event)
    if previous_project and current_project and previous_project != current_project:
        return False
    previous_app, current_app = _application(previous_event), _application(current_event)
    if previous_app and current_app and previous_app == current_app:
        return True
    previous_classes = _class_evidence(previous_event) - {"mixed"}
    current_classes = _class_evidence(current_event) - {"mixed"}
    if not previous_classes or not current_classes or previous_classes & current_classes:
        return True
    if {"coding", "terminal"} >= previous_classes | current_classes and (previous_project or current_project):
        return True
    return False


def _build_session(number: int, items: list[tuple[datetime, int, dict[str, Any]]]) -> dict[str, Any]:
    timestamps = [item[0] for item in items]
    events = [item[2] for item in items]
    classification, confidence = _classify(events)
    apps = sorted({_application_display_name(event) for event in events if _application_display_name(event)})
    return {
        "id": f"session-{number}",
        "startAt": _format_time(min(timestamps)),
        "endAt": _format_time(max(timestamps)),
        "classification": classification,
        "confidence": confidence,
        "apps": apps,
        "eventIds": [event.get("id") or f"event-{position}" for _, position, event in items],
    }


def _classify(events: list[dict[str, Any]]) -> tuple[str, float]:
    evidence = Counter(label for event in events for label in _class_evidence(event))
    if not evidence:
        return "mixed", 0.2
    if set(evidence) == {"idle"}:
        return "idle", min(1.0, 0.7 + 0.1 * len(events))
    evidence.pop("idle", None)
    if not evidence:
        return "idle", 0.7
    if set(evidence) <= {"coding", "terminal"}:
        label = "coding" if evidence["coding"] >= evidence["terminal"] else "terminal"
    elif len(evidence) == 1:
        label = next(iter(evidence))
    else:
        label = "mixed"
    total = sum(evidence.values())
    confidence = min(1.0, round(0.5 + (max(evidence.values()) / total) * 0.5, 2))
    return label if label in CLASSIFICATIONS else "mixed", confidence


def _format_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "+00:00")
