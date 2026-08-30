"""Judge a day's evidence for noteworthy facts about vault-tracked people and projects."""

from __future__ import annotations

import json
import pathlib

from src.analysis.narrative import compact_event, event_stamp, local_time, read_events, truncate
from src.providers.model_client import call_chat_completions


PROMPT = """You are reviewing one day of a personal activity journal to decide whether anything genuinely noteworthy happened involving a specific person or project already tracked in a personal knowledge vault.

Most days, most entities warrant nothing. Empty lists are the correct answer far more often than not. Do not restate telemetry: a branch name, a dirty-file count, or a commit hash is not noteworthy by itself — write what changed in human terms, or write nothing.

Use ONLY names from the supplied roster, copied verbatim into "name". If you cannot tell which roster entry a fact is about, omit it entirely. Never invent a name that is not in the roster.

Return only valid JSON with this shape:
{
  "people": [{"name": "RosterName", "note": "one factual paragraph", "evidence": ["observed fact"], "confidence": 0.0}],
  "projects": [{"name": "RosterName", "note": "one factual paragraph", "evidence": ["observed fact"], "confidence": 0.0}]
}
Do not invent intent, accomplishments, conversations, or conclusions. Do not reproduce verbatim message text or secrets. Mark uncertain interpretations through a lower confidence value."""


def compact_entity_event(event: dict) -> dict | None:
    if event.get("source") == "git-project":
        return {
            "t": local_time(event_stamp(event)),
            "type": "project",
            "path": event.get("projectPath") or "",
            "branch": event.get("branch"),
            "commit": event.get("latestCommit"),
            "message": truncate(event.get("latestCommitMessage") or "", 120),
            "changedFileCount": event.get("changedFileCount") or 0,
        }
    return compact_event(event)


def summarize_projects(events: list[dict]) -> list[dict]:
    projects: dict[str, dict] = {}
    for event in events:
        if event.get("type") != "project":
            continue
        path = event.get("path") or ""
        record = projects.setdefault(
            path,
            {"path": path, "name": pathlib.Path(path).name if path else "", "branches": [], "commits": [], "maxChangedFileCount": 0},
        )
        branch = event.get("branch")
        if branch and branch not in record["branches"]:
            record["branches"].append(branch)
        commit_hash = event.get("commit")
        if commit_hash and not any(commit["hash"] == commit_hash for commit in record["commits"]):
            record["commits"].append({"hash": commit_hash, "message": event.get("message") or ""})
        record["maxChangedFileCount"] = max(record["maxChangedFileCount"], event.get("changedFileCount") or 0)
    return list(projects.values())


def _read_narrative(journal_root: pathlib.Path, date: str) -> str | None:
    narrative_path = journal_root / "raw" / f"journal-{date}.json"
    if narrative_path.exists():
        try:
            data = json.loads(narrative_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict) and data.get("summary"):
            return str(data["summary"])
    daily_path = journal_root / "daily" / f"{date}.md"
    if daily_path.exists():
        content = daily_path.read_text(encoding="utf-8")
        marker = "## LLM narrative"
        if marker in content:
            return content.split(marker, 1)[1].strip()
    return None


def build_evidence(journal_root: pathlib.Path, date: str, roster: dict) -> dict:
    result = read_events(journal_root, date, compact=compact_entity_event, limit=1000)
    events = result["recent"]
    return {
        "date": date,
        "narrative": _read_narrative(journal_root, date),
        "projects": summarize_projects(events),
        "events": events,
        "roster": roster,
    }


def extract_entity_facts(provider: dict, evidence: dict, max_chars: int = 8000) -> dict:
    from src.analysis.narrative import parse_model_json

    events = list(evidence.get("events") or [])
    payload = {
        "date": evidence["date"],
        "narrative": evidence.get("narrative"),
        "projects": evidence.get("projects"),
        "roster": evidence.get("roster"),
        "events": events,
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    while len(serialized) > max_chars and len(events) > 5:
        events = events[len(events) // 3:]
        payload["events"] = events
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"Today's evidence:\n{serialized}"}]
    content = call_chat_completions(provider, messages, temperature=0.2)
    return parse_model_json(content)


def _validate_entries(entries) -> list[dict]:
    valid: list[dict] = []
    if not isinstance(entries, list):
        return valid
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        note = str(entry.get("note") or "").strip()
        if not name or len(note) < 40:
            continue
        evidence_list = entry.get("evidence")
        evidence_list = [str(item) for item in evidence_list] if isinstance(evidence_list, list) else []
        try:
            confidence = float(entry.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        valid.append({"name": name, "note": note, "evidence": evidence_list, "confidence": confidence})
    return valid


def validate_facts(payload: dict) -> dict:
    return {
        "people": _validate_entries(payload.get("people")),
        "projects": _validate_entries(payload.get("projects")),
    }
