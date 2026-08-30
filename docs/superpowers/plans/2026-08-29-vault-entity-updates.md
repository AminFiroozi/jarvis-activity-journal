# Vault Entity Companion Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a once-nightly, opt-in pipeline stage that judges (via LLM) whether anything noteworthy happened involving a person or project already tracked in the Obsidian vault, and appends at most one dated paragraph per resolved entity to a companion note — never touching the curated `People/<Name>.md` or `Projects/<Name>.md` files.

**Architecture:** `src/analysis/narrative.py` (new, shared evidence primitives extracted from `synthesize_journal.py`) → `src/analysis/entity_facts.py` (new, model-facing: evidence → LLM → validated facts, no vault knowledge) → `src/orchestration/sync_entities.py` (new, vault-facing: strict name resolution, idempotent companion-note writes, CLI). `vault_linker.py` gains a `build_note_paths` helper both `build_name_index` and the new resolver share.

**Tech Stack:** Python 3.10+, pytest, stdlib only plus the existing `src.providers.model_client`.

**Spec:** `docs/superpowers/specs/2026-08-29-vault-entity-updates-design.md`

## Global Constraints

- Every module is invoked as `python -m src.<subpackage>.<name>` — no bare-script imports, no try/except ImportError fallback patterns.
- Commits: conventional format (`feat:`/`fix:`/`test:`/`docs:`/`refactor:`), plain everyday words, authored as `AminFiroozi <afiroozi007@gmail.com>` — never a Claude co-author trailer.
- Run `python -m pytest tests/ -q` after every task; all tests must pass before moving to the next task.
- **No fuzzy/edit-distance/prefix/substring name matching, anywhere, ever.** `resolve_note_name` only accepts exact-stem, whole-token, separator-stripped, or word-intersection matches with exactly one surviving candidate. Anything else is dropped, never guessed.
- Every companion-note path is derived only from an already-resolved, already-existing note's real `.parent`/`.stem` plus a fixed suffix. No path component ever comes from model output. `date` is validated against `^\d{4}-\d{2}-\d{2}$` before use in any heading or path.
- Companion notes are append-only and idempotent: re-running the same date is a byte-for-byte no-op (skip, never replace, if that date's heading already exists).
- The curated `People/<Name>.md` / `Projects/<Name>.md` files are never opened for writing by any code in this plan.
- `sync_entities.py`'s `main()` never lets an exception escape — always exits 0, matching `sync_vault.py`'s existing contract exactly.
- `entityUpdates.enabled: false` and `activeProvider: "local-text"` by default in `config/settings.example.json` — this stage is off and on-device until explicitly opted into.

---

### Task 1: Extract shared evidence primitives into `narrative.py`

**Files:**
- Create: `src/analysis/narrative.py`
- Modify: `src/analysis/synthesize_journal.py`
- Test: `tests/test_narrative.py`

**Interfaces:**
- Consumes: `src.analysis.sessionize.detect_sessions(events: list[dict]) -> list[dict]` (already exists).
- Produces: `local_time(value: str | None) -> str`, `event_stamp(event: dict) -> str | None`, `truncate(text: str, limit: int) -> str`, `compact_event(event: dict) -> dict | None`, `compact_session(session: dict) -> dict`, `parse_model_json(content: str) -> dict`, `read_events(journal_root: pathlib.Path, date: str, compact: Callable[[dict], dict | None] = compact_event, limit: int = 60) -> dict` (returns `{"sessions": [...], "recent": [...]}`), `fit_evidence(sessions: list[dict], recent: list[dict], max_chars: int) -> tuple[list[dict], list[dict], str]` — all consumed by Task 3's `entity_facts.py` and by the refactored `synthesize_journal.py`.

This is a pure move — every function's body is copied verbatim from the current `synthesize_journal.py`, only `read_events` gains two new keyword parameters (`compact`, `limit`) with defaults matching today's hardcoded behavior exactly (`compact_event`, `60`), and the shrink loop from `call_model` is extracted into `fit_evidence`. Nothing changes for `synthesize_journal.py`'s own behavior.

- [ ] **Step 1: Write the failing test**

Create `tests/test_narrative.py`:

```python
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.analysis.narrative import (
    compact_event,
    compact_session,
    event_stamp,
    fit_evidence,
    local_time,
    parse_model_json,
    read_events,
    truncate,
)


class NarrativeTests(unittest.TestCase):
    def test_local_time_converts_utc_to_local(self):
        result = local_time("2026-08-23T10:00:00+00:00")
        expected = dt.datetime.fromisoformat("2026-08-23T10:00:00+00:00").astimezone().strftime("%H:%M")
        self.assertEqual(result, expected)

    def test_local_time_handles_missing_value(self):
        self.assertEqual(local_time(None), "")

    def test_event_stamp_prefers_local_timestamp(self):
        event = {"localTimestamp": "2026-08-23T10:00:00+03:30", "timestamp": "2026-08-23T06:30:00+00:00"}
        self.assertEqual(event_stamp(event), "2026-08-23T10:00:00+03:30")

    def test_truncate_adds_ellipsis_when_over_limit(self):
        self.assertEqual(truncate("hello world", 5), "hello…")
        self.assertEqual(truncate("hi", 5), "hi")

    def test_compact_event_handles_foreground_window(self):
        event = {"source": "foreground-window", "executable": "C:/Code.exe", "windowTitle": "main.py", "timestamp": "2026-08-23T10:00:00+00:00"}
        result = compact_event(event)
        self.assertEqual(result["type"], "window")
        self.assertEqual(result["app"], "Code")

    def test_compact_event_returns_none_for_git_project(self):
        event = {"source": "git-project", "projectPath": "/repo"}
        self.assertIsNone(compact_event(event))

    def test_compact_session_produces_a_compact_dict(self):
        session = {
            "startAt": "2026-08-23T10:00:00+00:00",
            "endAt": "2026-08-23T10:30:00+00:00",
            "classification": "coding",
            "apps": ["Code", "WindowsTerminal"],
            "confidence": 0.9,
        }
        result = compact_session(session)
        expected_start = dt.datetime.fromisoformat(session["startAt"]).astimezone().strftime("%H:%M")
        expected_end = dt.datetime.fromisoformat(session["endAt"]).astimezone().strftime("%H:%M")
        self.assertEqual(result["t"], f"{expected_start}-{expected_end}")
        self.assertNotIn("confidence", result)

    def test_parse_model_json_accepts_fenced_json(self):
        result = parse_model_json('```json\n{"summary":"ok"}\n```')
        self.assertEqual(result["summary"], "ok")

    def test_read_events_uses_default_compactor_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            events = [
                {"source": "foreground-window", "process": "Code", "timestamp": f"2026-08-23T{hour:02d}:00:00+00:00", "active": True}
                for hour in range(9, 18)
            ]
            (raw / "activity-2026-08-23.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

            result = read_events(journal, "2026-08-23")

            self.assertIn("sessions", result)
            self.assertEqual(len(result["recent"]), 9)

    def test_read_events_accepts_a_custom_compactor_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            events = [{"source": "git-project", "projectPath": "/repo", "timestamp": "2026-08-23T10:00:00+00:00"}]
            (raw / "activity-2026-08-23.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

            def custom_compact(event):
                return {"type": "project", "path": event.get("projectPath")} if event.get("source") == "git-project" else None

            result = read_events(journal, "2026-08-23", compact=custom_compact, limit=1000)

            self.assertEqual(len(result["recent"]), 1)
            self.assertEqual(result["recent"][0]["path"], "/repo")

    def test_fit_evidence_shrinks_recent_before_sessions(self):
        sessions = [{"t": "09:00-10:00", "class": "coding", "apps": []}] * 3
        recent = [{"t": "09:00", "type": "window", "app": "Code", "title": "x" * 50}] * 200
        shrunk_sessions, shrunk_recent, evidence = fit_evidence(sessions, recent, max_chars=2000)
        self.assertLessEqual(len(evidence), 2200)
        self.assertEqual(len(shrunk_sessions), 3)
        self.assertLess(len(shrunk_recent), 200)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_narrative.py -v`
Expected: FAIL — `src.analysis.narrative` does not exist yet.

- [ ] **Step 3: Create `narrative.py`**

Create `src/analysis/narrative.py`:

```python
"""Shared evidence primitives for LLM-narrative synthesis stages."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Callable

from src.analysis.sessionize import detect_sessions


def local_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        stamp = str(value)
        return stamp[11:16] if len(stamp) >= 16 else stamp
    return parsed.astimezone().strftime("%H:%M")


def event_stamp(event: dict) -> str | None:
    return event.get("localTimestamp") or event.get("timestamp")


def truncate(text: str, limit: int) -> str:
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def compact_event(event: dict) -> dict | None:
    source = event.get("source")
    if source == "foreground-window":
        exe = pathlib.Path(str(event.get("executable", ""))).stem or event.get("process", "")
        return {"t": local_time(event_stamp(event)), "type": "window", "app": exe, "title": truncate(event.get("windowTitle", ""), 60)}
    if source == "focused-content":
        return {"t": local_time(event_stamp(event)), "type": "content", "app": event.get("process", ""), "text": truncate(event.get("content", ""), 150)}
    if source == "screenshot-vision":
        analysis = event.get("analysis") or {}
        return {"t": local_time(event_stamp(event)), "type": "screen", "summary": truncate(analysis.get("summary", ""), 200), "apps": analysis.get("applications", []), "activity": analysis.get("activity_type", "")}
    return None


def compact_session(session: dict) -> dict:
    start = local_time(session.get("startAt"))
    end = local_time(session.get("endAt"))
    return {
        "t": f"{start}-{end}" if start and end else start or end,
        "class": session.get("classification", "unknown"),
        "apps": session.get("apps") or [],
    }


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


def read_events(
    journal_root: pathlib.Path,
    date: str,
    compact: Callable[[dict], dict | None] = compact_event,
    limit: int = 60,
) -> dict:
    raw_events: list[dict] = []
    compacted: list[dict] = []
    for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
        path = journal_root / "raw" / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                raw_events.append(record)
                event = compact(record)
                if event:
                    compacted.append(event)
    sessions = [compact_session(session) for session in detect_sessions(raw_events)]
    return {"sessions": sessions, "recent": compacted[-limit:]}


def fit_evidence(sessions: list[dict], recent: list[dict], max_chars: int) -> tuple[list[dict], list[dict], str]:
    evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    while len(evidence) > max_chars and len(recent) > 5:
        recent = recent[len(recent) // 3:]
        evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    while len(evidence) > max_chars and len(sessions) > 5:
        sessions = sessions[len(sessions) // 5:]
        evidence = json.dumps({"day_sessions": sessions, "recent_detail": recent}, ensure_ascii=False, separators=(",", ":"))
    return sessions, recent, evidence
```

- [ ] **Step 4: Refactor `synthesize_journal.py` to import from `narrative.py`**

Replace the top of `src/analysis/synthesize_journal.py` (imports through the `PROMPT` constant stay, everything between `PROMPT` and `main()` changes). Find:

```python
from src.analysis.sessionize import detect_sessions
from src.providers.model_client import ProviderError, call_chat_completions, resolve_provider
```

Replace with:

```python
from src.analysis.narrative import compact_event, compact_session, fit_evidence, local_time, parse_model_json, read_events, truncate
from src.providers.model_client import ProviderError, call_chat_completions, resolve_provider
```

Then delete these functions entirely from `synthesize_journal.py` (now imported instead): `parse_model_json`, `local_time`, `_event_stamp`, `truncate`, `compact_event`, `compact_session`, `read_events`. Keep `PROMPT`, `parse_args`, `upsert_narrative`, and `main` exactly as they are.

Replace `call_model`:

```python
def call_model(provider: dict, evidence_dict: dict) -> dict:
    sessions, recent, evidence = fit_evidence(evidence_dict["sessions"], evidence_dict["recent"], max_chars=6000)
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"Observed events for the day:\n{evidence}"}]
    content = call_chat_completions(provider, messages, temperature=0.2)
    return parse_model_json(content)
```

- [ ] **Step 5: Run tests to verify everything passes, including the untouched existing test file**

Run: `python -m pytest tests/test_narrative.py tests/test_synthesize_journal.py -v`
Expected: all PASS. `tests/test_synthesize_journal.py` is NOT modified in this task — it imports `compact_session` and `read_events` directly from `src.analysis.synthesize_journal`, which still works because Step 4's import line re-exports those names into that module's namespace. This is the proof the extraction is behavior-preserving.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/analysis/narrative.py src/analysis/synthesize_journal.py tests/test_narrative.py
git commit -m "refactor(analysis): extract shared evidence primitives into narrative.py"
```

---

### Task 2: `vault_linker.py` gains `build_note_paths` and excludes companion notes

**Files:**
- Modify: `src/orchestration/vault_linker.py`
- Test: `tests/test_vault_linker.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `build_note_paths(vault_root: pathlib.Path) -> dict[str, list[pathlib.Path]]` — consumed by Task 4's `sync_entities.py` for exact-stem lookup and category-gating (a stem's real file paths, so the resolver can check whether a match lands under `People/` or `Projects/`).

`build_name_index` becomes a thin wrapper over `build_note_paths` — identical output for every existing caller, verified by the untouched existing tests in this file.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_vault_linker.py` (uses the file's existing `_make_vault`-style fixture pattern — add these as new test methods in the existing `VaultLinkerTests` class):

```python
    def test_build_note_paths_maps_stem_to_real_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_vault(root)

            note_paths = build_note_paths(root)

            self.assertEqual([path.stem for path in note_paths["DariushSeif"]], ["DariushSeif"])
            self.assertTrue(note_paths["DariushSeif"][0].exists())

    def test_build_note_paths_excludes_companion_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_vault(root)
            (root / "People" / "Friends" / "DariushSeif - Activity Mentions.md").write_text("", encoding="utf-8")
            (root / "Projects" / "Mahoura - Activity Log.md").write_text("", encoding="utf-8")

            note_paths = build_note_paths(root)
            index = build_name_index(root)

            self.assertNotIn("DariushSeif - Activity Mentions", note_paths)
            self.assertNotIn("Mahoura - Activity Log", note_paths)
            self.assertNotIn("mentions", index)
```

(If `_make_vault` doesn't create a `Projects/Mahoura.md` fixture, add `(root / "Projects" / "Mahoura.md").write_text("", encoding="utf-8")` inside `_make_vault`, or inline it in this test — check the existing fixture first and reuse what's there rather than duplicating.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vault_linker.py -v`
Expected: FAIL — `build_note_paths` doesn't exist yet.

- [ ] **Step 3: Refactor `vault_linker.py`**

In `src/orchestration/vault_linker.py`, find:

```python
def build_name_index(vault_root: pathlib.Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for pattern in _NAME_GLOBS:
        for path in sorted(vault_root.glob(pattern)):
            if not path.is_file():
                continue
            if "History" in path.parts:
                continue
            base_name = path.stem
            for token in _split_tokens(base_name):
                candidates = index.setdefault(token, [])
                if base_name not in candidates:
                    candidates.append(base_name)
    return index
```

Replace with:

```python
_COMPANION_SUFFIXES = (" - Activity Mentions", " - Activity Log")


def _is_companion_note(stem: str) -> bool:
    return any(stem.endswith(suffix) for suffix in _COMPANION_SUFFIXES)


def build_note_paths(vault_root: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    note_paths: dict[str, list[pathlib.Path]] = {}
    for pattern in _NAME_GLOBS:
        for path in sorted(vault_root.glob(pattern)):
            if not path.is_file():
                continue
            if "History" in path.parts:
                continue
            if _is_companion_note(path.stem):
                continue
            note_paths.setdefault(path.stem, []).append(path)
    return note_paths


def build_name_index(vault_root: pathlib.Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for base_name in build_note_paths(vault_root):
        for token in _split_tokens(base_name):
            candidates = index.setdefault(token, [])
            if base_name not in candidates:
                candidates.append(base_name)
    return index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vault_linker.py -v`
Expected: all PASS, including every pre-existing test in this file (proof the refactor preserves `build_name_index`'s exact output).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/orchestration/vault_linker.py tests/test_vault_linker.py
git commit -m "feat(vault-linker): expose note paths and exclude generated companion notes"
```

---

### Task 3: `entity_facts.py` — evidence gathering and the LLM call

**Files:**
- Create: `src/analysis/entity_facts.py`
- Test: `tests/test_entity_facts.py`

**Interfaces:**
- Consumes: `src.analysis.narrative.{compact_event, event_stamp, local_time, truncate, parse_model_json, read_events}` (Task 1), `src.providers.model_client.call_chat_completions(provider, messages, temperature) -> str` (already exists).
- Produces: `compact_entity_event(event) -> dict | None`, `summarize_projects(events: list[dict]) -> list[dict]`, `build_evidence(journal_root, date, roster) -> dict`, `extract_entity_facts(provider, evidence, max_chars=8000) -> dict`, `validate_facts(payload) -> dict` — all consumed by Task 4's `sync_entities.py`. No vault knowledge, no file writes into the vault, no name resolution (that is `sync_entities.py`'s job).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_facts.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analysis.entity_facts import (
    build_evidence,
    compact_entity_event,
    extract_entity_facts,
    summarize_projects,
    validate_facts,
)


class CompactEntityEventTests(unittest.TestCase):
    def test_compacts_git_project_events(self):
        event = {
            "source": "git-project",
            "projectPath": "/repo/mahoura",
            "branch": "main",
            "latestCommit": "abc123",
            "latestCommitMessage": "fix bug",
            "changedFileCount": 3,
            "timestamp": "2026-08-23T10:00:00+00:00",
        }
        result = compact_entity_event(event)
        self.assertEqual(result["type"], "project")
        self.assertEqual(result["path"], "/repo/mahoura")
        self.assertEqual(result["commit"], "abc123")

    def test_delegates_other_sources_to_narrative_compact_event(self):
        event = {"source": "foreground-window", "process": "Code", "timestamp": "2026-08-23T10:00:00+00:00"}
        result = compact_entity_event(event)
        self.assertEqual(result["type"], "window")


class SummarizeProjectsTests(unittest.TestCase):
    def test_collapses_repeated_snapshots_into_one_record_per_path(self):
        events = [
            {"type": "project", "path": "/repo/mahoura", "branch": "main", "commit": "abc123", "message": "fix bug", "changedFileCount": 2},
            {"type": "project", "path": "/repo/mahoura", "branch": "main", "commit": "abc123", "message": "fix bug", "changedFileCount": 5},
            {"type": "project", "path": "/repo/mahoura", "branch": "main", "commit": "def456", "message": "add feature", "changedFileCount": 1},
            {"type": "window", "app": "Code"},
        ]
        result = summarize_projects(events)
        self.assertEqual(len(result), 1)
        record = result[0]
        self.assertEqual(record["path"], "/repo/mahoura")
        self.assertEqual(record["name"], "mahoura")
        self.assertEqual(record["maxChangedFileCount"], 5)
        self.assertEqual([c["hash"] for c in record["commits"]], ["abc123", "def456"])

    def test_empty_events_produce_empty_list(self):
        self.assertEqual(summarize_projects([]), [])


class BuildEvidenceTests(unittest.TestCase):
    def test_prefers_the_synthesized_narrative_json(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "raw").mkdir()
            (journal / "raw" / "journal-2026-08-23.json").write_text(json.dumps({"summary": "Worked on Mahoura with Dariush."}), encoding="utf-8")

            evidence = build_evidence(journal, "2026-08-23", roster={"people": ["DariushSeif"], "projects": ["Mahoura"]})

            self.assertEqual(evidence["narrative"], "Worked on Mahoura with Dariush.")
            self.assertEqual(evidence["roster"]["people"], ["DariushSeif"])

    def test_falls_back_to_daily_markdown_narrative_section(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "daily").mkdir()
            (journal / "daily" / "2026-08-23.md").write_text("# Journal\n\n## LLM narrative\n\nWorked on Mahoura.\n", encoding="utf-8")

            evidence = build_evidence(journal, "2026-08-23", roster={"people": [], "projects": []})

            self.assertIn("Worked on Mahoura.", evidence["narrative"])

    def test_narrative_is_none_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = build_evidence(Path(directory), "2026-08-23", roster={"people": [], "projects": []})
            self.assertIsNone(evidence["narrative"])


class ExtractEntityFactsTests(unittest.TestCase):
    def test_parses_the_model_response(self):
        provider = {"name": "test"}
        evidence = {"date": "2026-08-23", "narrative": "text", "projects": [], "roster": {"people": [], "projects": []}, "events": []}
        canned = json.dumps({"people": [{"name": "DariushSeif", "note": "x" * 50, "confidence": 0.8}], "projects": []})
        with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned) as mocked:
            result = extract_entity_facts(provider, evidence)
        self.assertEqual(result["people"][0]["name"], "DariushSeif")
        mocked.assert_called_once()


class ValidateFactsTests(unittest.TestCase):
    def test_drops_entries_with_blank_name_or_short_note(self):
        payload = {
            "people": [{"name": "", "note": "x" * 50}, {"name": "DariushSeif", "note": "too short"}, {"name": "Mahoura", "note": "x" * 50, "confidence": 0.7}],
            "projects": "not-a-list",
        }
        result = validate_facts(payload)
        self.assertEqual(len(result["people"]), 1)
        self.assertEqual(result["people"][0]["name"], "Mahoura")
        self.assertEqual(result["projects"], [])

    def test_defaults_confidence_and_evidence(self):
        payload = {"people": [{"name": "X", "note": "y" * 50}], "projects": []}
        result = validate_facts(payload)
        self.assertEqual(result["people"][0]["confidence"], 0.0)
        self.assertEqual(result["people"][0]["evidence"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_entity_facts.py -v`
Expected: FAIL — `src.analysis.entity_facts` does not exist yet.

- [ ] **Step 3: Create `entity_facts.py`**

Create `src/analysis/entity_facts.py`:

```python
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
```

Note: `parse_model_json` is imported locally inside `extract_entity_facts` rather than at module top level — purely to keep the module-top import block limited to what's used at definition time; `call_chat_completions` IS imported at module top level, which is what the test's `mock.patch("src.analysis.entity_facts.call_chat_completions", ...)` patches.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_entity_facts.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/analysis/entity_facts.py tests/test_entity_facts.py
git commit -m "feat(analysis): judge daily entity noteworthiness from vault-scoped evidence"
```

---

### Task 4: `sync_entities.py` — name resolution and companion-note writes

**Files:**
- Create: `src/orchestration/sync_entities.py`
- Test: `tests/test_sync_entities.py`

**Interfaces:**
- Consumes: `src.orchestration.vault_linker.{build_name_index, build_note_paths, inject_links}` (Task 2), `src.analysis.entity_facts.{build_evidence, extract_entity_facts, validate_facts}` (Task 3), `src.infra.heartbeat.write_heartbeat` (already exists), `src.providers.model_client.resolve_provider` (already exists).
- Produces: `resolve_note_name(proposed, index, note_paths, category) -> pathlib.Path | None`, `companion_path(note_path, category) -> pathlib.Path`, `append_entry(path, stem, category, date, entry_body) -> pathlib.Path | None`, `sync_entities(journal_root, vault_root, config, date, dry_run=False) -> dict`, CLI `main()`.

**This is the task where review attention matters most** — the resolver is the sole boundary preventing a wrong-entity write.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sync_entities.py`:

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.orchestration.sync_entities import (
    append_entry,
    companion_path,
    main,
    resolve_note_name,
    sync_entities,
)
from src.orchestration.vault_linker import build_name_index, build_note_paths


def _make_vault(root: Path) -> None:
    friends = root / "People" / "Friends"
    friends.mkdir(parents=True)
    (friends / "DariushSeif.md").write_text("curated content\n", encoding="utf-8")
    (friends / "ErfanMoayed.md").write_text("", encoding="utf-8")
    (friends / "ErfanTajik.md").write_text("", encoding="utf-8")
    projects = root / "Projects"
    projects.mkdir()
    (projects / "Mahoura.md").write_text("curated content\n", encoding="utf-8")
    skills = root / "Skills"
    skills.mkdir()
    (skills / "Python.md").write_text("", encoding="utf-8")


class ResolveNoteNameTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        _make_vault(self.root)
        self.index = build_name_index(self.root)
        self.note_paths = build_note_paths(self.root)

    def tearDown(self):
        self.directory.cleanup()

    def test_resolves_exact_stem(self):
        result = resolve_note_name("DariushSeif", self.index, self.note_paths, "people")
        self.assertEqual(result.stem, "DariushSeif")

    def test_resolves_single_token(self):
        result = resolve_note_name("Dariush", self.index, self.note_paths, "people")
        self.assertEqual(result.stem, "DariushSeif")

    def test_resolves_separator_stripped_name(self):
        result = resolve_note_name("Dariush Seif", self.index, self.note_paths, "people")
        self.assertEqual(result.stem, "DariushSeif")

    def test_drops_ambiguous_shared_first_name(self):
        result = resolve_note_name("Erfan", self.index, self.note_paths, "people")
        self.assertIsNone(result)

    def test_drops_unknown_name(self):
        result = resolve_note_name("SomeoneNotInTheVault", self.index, self.note_paths, "people")
        self.assertIsNone(result)

    def test_drops_category_mismatch(self):
        result = resolve_note_name("Python", self.index, self.note_paths, "projects")
        self.assertIsNone(result)

    def test_person_never_resolves_under_projects(self):
        result = resolve_note_name("Mahoura", self.index, self.note_paths, "people")
        self.assertIsNone(result)


class CompanionPathTests(unittest.TestCase):
    def test_person_companion_lives_beside_the_curated_note(self):
        note_path = Path("/vault/People/Friends/DariushSeif.md")
        result = companion_path(note_path, "people")
        self.assertEqual(result, Path("/vault/People/Friends/DariushSeif - Activity Mentions.md"))

    def test_project_companion_lives_beside_the_curated_note(self):
        note_path = Path("/vault/Projects/Mahoura.md")
        result = companion_path(note_path, "projects")
        self.assertEqual(result, Path("/vault/Projects/Mahoura - Activity Log.md"))


class AppendEntryTests(unittest.TestCase):
    def test_creates_file_with_header_and_backlink_on_first_write(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "DariushSeif - Activity Mentions.md"
            result = append_entry(target, "DariushSeif", "people", "2026-08-23", "## 2026-08-23\n\nSome note.\n")
            self.assertEqual(result, target)
            content = target.read_text(encoding="utf-8")
            self.assertIn("[[DariushSeif]]", content)
            self.assertIn("## 2026-08-23", content)

    def test_second_date_appends_a_second_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "DariushSeif - Activity Mentions.md"
            append_entry(target, "DariushSeif", "people", "2026-08-23", "## 2026-08-23\n\nFirst.\n")
            append_entry(target, "DariushSeif", "people", "2026-08-24", "## 2026-08-24\n\nSecond.\n")
            content = target.read_text(encoding="utf-8")
            self.assertIn("## 2026-08-23", content)
            self.assertIn("## 2026-08-24", content)

    def test_rerunning_the_same_date_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "DariushSeif - Activity Mentions.md"
            append_entry(target, "DariushSeif", "people", "2026-08-23", "## 2026-08-23\n\nFirst.\n")
            before = target.read_text(encoding="utf-8")
            second_result = append_entry(target, "DariushSeif", "people", "2026-08-23", "## 2026-08-23\n\nDifferent text.\n")
            after = target.read_text(encoding="utf-8")
            self.assertIsNone(second_result)
            self.assertEqual(before, after)


class SyncEntitiesTests(unittest.TestCase):
    def _config(self, **overrides):
        base = {"entityUpdates": {"enabled": True, "activeProvider": "test-provider", "minConfidence": 0.0, "maxEntitiesPerDay": 5}, "providers": {"test-provider": {"endpoint": "http://x", "model": "m"}}}
        base["entityUpdates"].update(overrides)
        return base

    def test_disabled_by_default_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            result = sync_entities(journal, vault, {"entityUpdates": {"enabled": False}}, "2026-08-23")
            self.assertEqual(result["status"], "disabled")
            self.assertFalse((vault / "People" / "Friends" / "DariushSeif - Activity Mentions.md").exists())

    def test_invalid_date_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = sync_entities(root / "journal", root / "vault", self._config(), "../../escaped")
            self.assertEqual(result["status"], "invalid-date")

    def test_end_to_end_writes_companion_note_and_leaves_curated_note_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            curated_before = (vault / "People" / "Friends" / "DariushSeif.md").read_text(encoding="utf-8")

            canned = json.dumps({
                "people": [{"name": "DariushSeif", "note": "Dariush reviewed a pull request on the Mahoura project today.", "evidence": ["reviewed PR"], "confidence": 0.8}],
                "projects": [],
            })
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(), "2026-08-23")

            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(result["written"]), 1)
            companion = vault / "People" / "Friends" / "DariushSeif - Activity Mentions.md"
            self.assertTrue(companion.exists())
            self.assertIn("reviewed a pull request", companion.read_text(encoding="utf-8"))
            self.assertIn("[[Mahoura]]", companion.read_text(encoding="utf-8"))
            curated_after = (vault / "People" / "Friends" / "DariushSeif.md").read_text(encoding="utf-8")
            self.assertEqual(curated_before, curated_after)

    def test_ambiguous_name_is_skipped_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            canned = json.dumps({"people": [{"name": "Erfan", "note": "x" * 50, "confidence": 0.9}], "projects": []})
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(), "2026-08-23")
            self.assertEqual(result["written"], [])
            self.assertEqual(result["skipped"][0]["reason"], "unresolved-or-ambiguous")

    def test_max_entities_per_day_caps_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            (vault / "People" / "Friends" / "AnotherPerson.md").write_text("", encoding="utf-8")
            canned = json.dumps({
                "people": [
                    {"name": "DariushSeif", "note": "x" * 50, "confidence": 0.9},
                    {"name": "AnotherPerson", "note": "y" * 50, "confidence": 0.5},
                ],
                "projects": [],
            })
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(maxEntitiesPerDay=1), "2026-08-23")
            self.assertEqual(len(result["written"]), 1)
            self.assertEqual(result["written"][0]["name"], "DariushSeif")

    def test_dry_run_writes_status_but_nothing_under_the_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            canned = json.dumps({"people": [{"name": "DariushSeif", "note": "x" * 50, "confidence": 0.9}], "projects": []})
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(), "2026-08-23", dry_run=True)
            self.assertEqual(len(result["written"]), 1)
            self.assertFalse((vault / "People" / "Friends" / "DariushSeif - Activity Mentions.md").exists())


class MainTests(unittest.TestCase):
    def test_main_exits_zero_on_malformed_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            vault.mkdir()
            config_path = root / "settings.json"
            config_path.write_text("not valid json", encoding="utf-8")
            old_argv = sys.argv
            sys.argv = ["sync_entities", "--journal-root", str(journal), "--config", str(config_path), "--vault-root", str(vault), "--date", "2026-08-23"]
            try:
                exit_code = main()
            finally:
                sys.argv = old_argv
            self.assertEqual(exit_code, 0)

    def test_main_exits_zero_when_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            vault.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({"entityUpdates": {"enabled": False}}), encoding="utf-8")
            old_argv = sys.argv
            sys.argv = ["sync_entities", "--journal-root", str(journal), "--config", str(config_path), "--vault-root", str(vault), "--date", "2026-08-23"]
            try:
                exit_code = main()
            finally:
                sys.argv = old_argv
            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_entities.py -v`
Expected: FAIL — `src.orchestration.sync_entities` does not exist yet.

- [ ] **Step 3: Create `sync_entities.py`**

Create `src/orchestration/sync_entities.py`:

```python
"""Judge daily entity noteworthiness and append companion notes to the Obsidian vault."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re

from src.analysis.entity_facts import build_evidence, extract_entity_facts, validate_facts
from src.infra.heartbeat import write_heartbeat
from src.orchestration.vault_linker import build_name_index, build_note_paths, inject_links
from src.providers.model_client import resolve_provider

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CATEGORY_ROOTS = {"people": "People", "projects": "Projects"}


def _filter_by_category(paths: list[pathlib.Path], category: str) -> list[pathlib.Path]:
    root_name = _CATEGORY_ROOTS[category]
    return [path for path in paths if root_name in path.parts]


def _resolve_candidates(candidates: list[str] | None, note_paths: dict[str, list[pathlib.Path]], category: str) -> pathlib.Path | None:
    if not candidates or len(candidates) != 1:
        return None
    matches = _filter_by_category(note_paths.get(candidates[0], []), category)
    return matches[0] if len(matches) == 1 else None


def resolve_note_name(
    proposed: str,
    index: dict[str, list[str]],
    note_paths: dict[str, list[pathlib.Path]],
    category: str,
) -> pathlib.Path | None:
    name = " ".join(str(proposed).split()).strip()
    if not name:
        return None
    lowered = name.lower()

    for stem, paths in note_paths.items():
        if stem.lower() == lowered:
            matches = _filter_by_category(paths, category)
            return matches[0] if len(matches) == 1 else None

    resolved = _resolve_candidates(index.get(lowered), note_paths, category)
    if resolved is not None:
        return resolved

    stripped = re.sub(r"[ _-]", "", name).lower()
    if stripped != lowered:
        resolved = _resolve_candidates(index.get(stripped), note_paths, category)
        if resolved is not None:
            return resolved

    words = [word.lower() for word in re.split(r"[ _-]+", name) if len(word) >= 3]
    if len(words) >= 2:
        candidate_sets = [set(index.get(word, [])) for word in words]
        if all(candidate_sets):
            intersection = sorted(set.intersection(*candidate_sets))
            resolved = _resolve_candidates(intersection, note_paths, category)
            if resolved is not None:
                return resolved

    return None


def companion_path(note_path: pathlib.Path, category: str) -> pathlib.Path:
    suffix = " - Activity Mentions" if category == "people" else " - Activity Log"
    return note_path.parent / f"{note_path.stem}{suffix}.md"


def render_companion_header(stem: str, category: str) -> str:
    label = "Activity Mentions" if category == "people" else "Activity Log"
    entity_type = "person" if category == "people" else "project"
    return (
        f'---\nentity: {stem}\ntype: {entity_type}\nup: "[[{stem}]]"\ntags: [activity-journal, generated]\n---\n\n'
        f"# {stem} — {label}\n\n"
        f"Auto-generated companion log for [[{stem}]]. Appended by the activity journal; the curated note is never modified.\n"
    )


def render_entry(date: str, note: str, evidence: list[str], confidence: float) -> str:
    lines = [f"## {date}", "", note.strip(), ""]
    if evidence:
        lines.append(f"_Evidence: {'; '.join(evidence)}_")
    lines.append(f"_Source: [[Journal/Daily/{date}|daily journal]] · confidence: {confidence}_")
    return "\n".join(lines).rstrip() + "\n"


def append_entry(path: pathlib.Path, stem: str, category: str, date: str, entry_body: str) -> pathlib.Path | None:
    heading_pattern = re.compile(rf"^## {re.escape(date)}\s*$", re.MULTILINE)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if heading_pattern.search(existing):
            return None
        updated = existing.rstrip() + "\n\n" + entry_body
    else:
        updated = render_companion_header(stem, category) + "\n" + entry_body
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return path


def sync_entities(journal_root: pathlib.Path, vault_root: pathlib.Path, config: dict, date: str, dry_run: bool = False) -> dict:
    if not _DATE_PATTERN.match(date):
        return {"date": date, "status": "invalid-date", "written": [], "skipped": []}

    stage_config = config.get("entityUpdates") or {}
    if not stage_config.get("enabled"):
        return {"date": date, "status": "disabled", "written": [], "skipped": []}

    note_paths = build_note_paths(vault_root)
    index = build_name_index(vault_root)
    roster = {
        "people": sorted({stem for stem, paths in note_paths.items() if _filter_by_category(paths, "people")}),
        "projects": sorted({stem for stem, paths in note_paths.items() if _filter_by_category(paths, "projects")}),
    }

    evidence = build_evidence(journal_root, date, roster)
    provider = resolve_provider(config, "entityUpdates")
    raw_payload = extract_entity_facts(provider, evidence, max_chars=int(stage_config.get("maxEvidenceChars", 8000)))

    raw_path = journal_root / "raw" / f"entities-{date}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validated = validate_facts(raw_payload)
    min_confidence = float(stage_config.get("minConfidence", 0.0))
    max_per_day = int(stage_config.get("maxEntitiesPerDay", 5))

    written: list[dict] = []
    skipped: list[dict] = []
    for category in ("people", "projects"):
        resolved: dict[pathlib.Path, dict] = {}
        for entry in validated[category]:
            if entry["confidence"] < min_confidence:
                skipped.append({"name": entry["name"], "category": category, "reason": "below-min-confidence"})
                continue
            note_path = resolve_note_name(entry["name"], index, note_paths, category)
            if note_path is None:
                skipped.append({"name": entry["name"], "category": category, "reason": "unresolved-or-ambiguous"})
                continue
            existing = resolved.get(note_path)
            if existing is None or entry["confidence"] > existing["confidence"]:
                resolved[note_path] = entry
        ranked = sorted(resolved.items(), key=lambda item: item[1]["confidence"], reverse=True)[:max_per_day]
        for note_path, entry in ranked:
            note_text = inject_links(entry["note"], index)
            entry_body = render_entry(date, note_text, entry["evidence"], entry["confidence"])
            target = companion_path(note_path, category)
            if dry_run:
                written.append({"name": note_path.stem, "category": category, "path": str(target)})
                continue
            result_path = append_entry(target, note_path.stem, category, date, entry_body)
            if result_path is None:
                skipped.append({"name": note_path.stem, "category": category, "reason": "already-present"})
            else:
                written.append({"name": note_path.stem, "category": category, "path": str(result_path)})

    status = {"date": date, "status": "complete", "written": written, "skipped": skipped}
    status_path = journal_root / "raw" / f"entities-{date}.status.json"
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--vault-root", required=True, type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Entity sync failed: {error}")
        return 0
    try:
        result = sync_entities(args.journal_root, args.vault_root, config, args.date, dry_run=args.dry_run)
    except Exception as error:  # sync must never fail the nightly pipeline
        write_heartbeat(args.journal_root, "entity-updates", "failed", error_message=str(error))
        print(f"Entity sync failed: {error}")
        return 0
    if result.get("status") == "complete":
        write_heartbeat(args.journal_root, "entity-updates", "success", items_processed=len(result.get("written", [])))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sync_entities.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/orchestration/sync_entities.py tests/test_sync_entities.py
git commit -m "feat(orchestration): append daily entity notes to vault companion files"
```

---

### Task 5: Wire into `daily_summary.py` and document the config

**Files:**
- Modify: `src/orchestration/daily_summary.py`
- Modify: `config/settings.example.json`
- Test: `tests/test_daily_summary.py`

**Interfaces:**
- Consumes: `src.orchestration.sync_entities` module (Task 4), invoked via `subprocess.run` exactly like `sync_vault` already is.
- Produces: nothing new for other tasks — this is the final wiring.

- [ ] **Step 1: Write the failing test**

Read `tests/test_daily_summary.py` first to match its existing style for the `sync_vault` gating tests (it already has this pattern for `sync_vault` — mirror it exactly for `sync_entities`, reusing whatever mocking/fixture helpers it already defines). Add test methods equivalent to:

```python
    def test_sync_entities_invoked_when_vault_root_set(self):
        # Mirror this file's existing "sync_vault invoked when vaultRoot set" test:
        # mock subprocess.run, assert one of the calls targets "src.orchestration.sync_entities"
        # with --journal-root/--config/--vault-root/--date matching the other vault-sync call.
        ...

    def test_sync_entities_not_invoked_when_vault_root_absent(self):
        # Mirror this file's existing "sync_vault not invoked" test the same way.
        ...
```

(Write these two tests using this file's actual existing mocking idiom — read the file's current `sync_vault`-gating tests first and copy their exact structure rather than guessing at one; the two features share the identical gate so the tests should be near-identical in shape.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daily_summary.py -v`
Expected: FAIL — `sync_entities` is not invoked yet.

- [ ] **Step 3: Wire `daily_summary.py`**

In `src/orchestration/daily_summary.py`, find:

```python
    if vault_root:
        subprocess.run([sys.executable, "-m", "src.orchestration.sync_vault", "--journal-root", str(args.journal_root), "--vault-root", str(vault_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
```

Replace with:

```python
    if vault_root:
        subprocess.run([sys.executable, "-m", "src.orchestration.sync_vault", "--journal-root", str(args.journal_root), "--vault-root", str(vault_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
        subprocess.run([sys.executable, "-m", "src.orchestration.sync_entities", "--journal-root", str(args.journal_root), "--config", str(args.config), "--vault-root", str(vault_root), "--date", args.date], cwd=pathlib.Path(__file__).parents[2])
```

- [ ] **Step 4: Document the new config stage**

In `config/settings.example.json`, add a new `entityUpdates` key alongside the existing `journalSynthesis` key:

```json
  "journalSynthesis": {
    "enabled": true,
    "activeProvider": "local-text"
  },
  "entityUpdates": {
    "enabled": false,
    "activeProvider": "local-text",
    "minConfidence": 0.0,
    "maxEntitiesPerDay": 5,
    "maxEvidenceChars": 8000
  },
```

(Match this file's exact existing indentation and key ordering conventions — insert it as a sibling of `journalSynthesis`, not nested inside it.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_daily_summary.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/orchestration/daily_summary.py config/settings.example.json tests/test_daily_summary.py
git commit -m "feat(daily-summary): run entity note sync behind the vaultRoot gate"
```

---

### Task 6: Document in README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed elsewhere — pure documentation.

- [ ] **Step 1: Update the architecture/pipeline description and the `vaultRoot` paragraph**

Read the current `README.md` sections describing the pipeline architecture (the `Screenshot → vision model → ...` diagram near the top) and the `vaultRoot`-mentioning paragraph added by the previous vault-sync feature. Add:
- One line to the architecture diagram or the surrounding prose noting that, when `vaultRoot` and `entityUpdates.enabled` are both set, the daily narrative is also checked for noteworthy person/project facts and appended to companion notes (`<Name> - Activity Mentions.md` / `<Name> - Activity Log.md`) beside — never inside — the curated vault notes.
- A short clause after the existing `vaultRoot` explanation clarifying that this is a separate opt-in (`entityUpdates.enabled`) on top of `vaultRoot`, defaults to off and to the local provider, and never modifies a curated note.

There is no fixed line number to target here since the file may have shifted — read it fresh and place these additions where they read naturally alongside the existing `vaultRoot`/vault-sync documentation.

- [ ] **Step 2: Run the full suite** (documentation change, but confirm nothing else broke)

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document vault entity companion notes"
```

---

## Self-Review

**Spec coverage:** companion-notes-only for both People/Projects (Tasks 2 and 4) ✓; LLM-judged noteworthiness with silence as the default (Task 3's `PROMPT`) ✓; no fuzzy matching, strict resolver with category gating (Task 4's `resolve_note_name`) ✓; idempotent skip-not-replace (Task 4's `append_entry`) ✓; path-safety invariant — every companion path built from an already-resolved existing file, date regex-validated (Task 4) ✓; once-nightly cadence wired into `daily_summary.py` after both `synthesize_journal` and `sync_vault` (Task 5) ✓; `enabled: false`/`local-text` defaults, `maxEntitiesPerDay` cap (Task 5) ✓; observability via heartbeat + status JSON with a `skipped` reasons list (Task 4) ✓.

**Placeholder scan:** no TBD/TODO; every step has real, complete code, except Task 5 Step 1 and Task 6 Step 1, which deliberately point at "read the existing file's pattern first" rather than guessing at exact current line numbers/test helper names that may have shifted since this plan was written — both are narrow, mechanical lookups, not open design.

**Type consistency:** `read_events`'s new `compact`/`limit` parameters (Task 1) are used identically by `synthesize_journal.call_model` (default args, unchanged behavior) and `entity_facts.build_evidence` (custom compactor, `limit=1000`) — checked both call sites match the signature defined in Task 1. `resolve_note_name`'s `category` parameter (`"people"`/`"projects"`) is used consistently across `sync_entities`, `_filter_by_category`, and `companion_path`. `build_note_paths`' return shape (`dict[str, list[pathlib.Path]]`) is what Task 4's resolver expects; `build_name_index`'s return shape (`dict[str, list[str]]`) is unchanged from what `inject_links` and Task 4's resolver both already expect.
