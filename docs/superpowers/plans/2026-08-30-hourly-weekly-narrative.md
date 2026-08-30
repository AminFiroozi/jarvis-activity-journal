# Hourly/Weekly Narrative Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** replace the deterministic session+evidence-dump renderer for hourly/weekly journals with an LLM narrative matching `daily/<date>.md`'s format, with a retry queue for LLM failures and a guard so genuinely empty hours never trigger a wasted/fabrication-prone model call.

**Architecture:** one new module `src/analysis/synthesize_period.py` (mirrors `synthesize_journal.py`'s single-file shape: evidence-gathering, LLM call, markdown write, all in one place), reusing `src/analysis/narrative.py`'s shared primitives. Wired into `run_hourly.py` in place of the deleted deterministic renderer. A dedicated `FileJobQueue` root (`Journal/queue-period/`) handles retry-on-failure, mirroring `analyze_screenshots.py`'s existing queue pattern exactly.

**Tech Stack:** Python 3.10+, pytest, stdlib only plus `src.providers.model_client` and `src.infra.processing_queue`.

**Spec:** `docs/superpowers/specs/2026-08-30-hourly-weekly-narrative-design.md`

## Global Constraints

- Every module is invoked as `python -m src.<subpackage>.<name>` — no bare-script imports, no try/except ImportError fallback patterns.
- Commits: conventional format (`feat:`/`fix:`/`test:`/`docs:`/`refactor:`), plain everyday words, authored as `AminFiroozi <afiroozi007@gmail.com>` — never a Claude co-author trailer.
- Run `python -m pytest tests/ -q` after every task; all tests must pass before moving to the next task.
- The narrative format must match daily's exact section shape: summary paragraph, `### Timeline`, `### Patterns`, `### Next actions`, `_LLM confidence: N_` — no Accomplishments/Blockers sections (per `rules/hourly-weekly-narrative-format.md`, which lists only Timeline/Patterns/Next actions).
- An hour is skipped (no LLM call, nothing written, nothing queued) only when there is truly zero evidence: no activity/content/visual JSONL events for that hour AND no screenshot file captured in that hour. A screenshot alone counts as evidence even if vision analysis hasn't processed it yet.
- On LLM failure (network, rate limit, provider error) — not on zero-evidence — the period is enqueued via `FileJobQueue` for retry, never silently dropped.
- `main()` never lets an exception escape — always exits 0, matching `sync_vault.py`/`analyze_screenshots.py`'s existing non-fatal contract.
- `build_journals.py`, `journalize.py`, and `tests/test_journalize.py` are deleted once nothing calls them — confirmed today that only their own test file references them.

---

### Task 1: Evidence gathering and rendering primitives in `synthesize_period.py`

**Files:**
- Create: `src/analysis/synthesize_period.py` (started in this task, extended in Task 2)
- Test: `tests/test_synthesize_period.py` (started in this task, extended in Task 2)

**Interfaces:**
- Consumes: `src.analysis.narrative.{compact_event, compact_session, event_stamp, parse_model_json, fit_evidence}` (already exist), `src.analysis.sessionize.detect_sessions` (already exists).
- Produces: `read_period_events(journal_root, dates, hour=None, compact=compact_event, limit=1000) -> dict`, `has_evidence_for_hour(journal_root, date, hour) -> bool`, `week_dates(date) -> tuple[int, int, list[str]]`, `render_period_document(title, narrative) -> str`, `call_model(provider, evidence_dict, prompt, max_chars=6000) -> dict`, `HOURLY_PROMPT`, `WEEKLY_PROMPT` module constants — all consumed by Task 2's `synthesize_hour`/`synthesize_week`/`main()` in the same file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_synthesize_period.py`:

```python
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.analysis.synthesize_period import (
    HOURLY_PROMPT,
    WEEKLY_PROMPT,
    call_model,
    has_evidence_for_hour,
    read_period_events,
    render_period_document,
    week_dates,
)


class ReadPeriodEventsTests(unittest.TestCase):
    def test_single_date_no_hour_filter_matches_narrative_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            events = [
                {"source": "foreground-window", "process": "Code", "timestamp": f"2026-08-23T{hour:02d}:00:00+00:00", "active": True}
                for hour in range(9, 18)
            ]
            (raw / "activity-2026-08-23.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

            result = read_period_events(journal, ["2026-08-23"])

            self.assertIn("sessions", result)
            self.assertIn("recent", result)
            self.assertEqual(len(result["recent"]), 9)

    def test_hour_filter_excludes_events_outside_the_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            events = [
                {"source": "foreground-window", "process": "Code", "localTimestamp": "2026-08-23T09:15:00+03:30", "active": True},
                {"source": "foreground-window", "process": "Code", "localTimestamp": "2026-08-23T09:45:00+03:30", "active": True},
                {"source": "foreground-window", "process": "Chrome", "localTimestamp": "2026-08-23T10:05:00+03:30", "active": True},
            ]
            (raw / "activity-2026-08-23.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

            result = read_period_events(journal, ["2026-08-23"], hour=9)

            self.assertEqual(len(result["recent"]), 2)
            self.assertTrue(all(item["app"] == "Code" for item in result["recent"]))

    def test_multi_date_span_merges_events_across_days(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            (raw / "activity-2026-08-23.jsonl").write_text(
                json.dumps({"source": "foreground-window", "process": "Code", "localTimestamp": "2026-08-23T09:00:00+03:30", "active": True}) + "\n",
                encoding="utf-8",
            )
            (raw / "activity-2026-08-24.jsonl").write_text(
                json.dumps({"source": "foreground-window", "process": "Chrome", "localTimestamp": "2026-08-24T10:00:00+03:30", "active": True}) + "\n",
                encoding="utf-8",
            )

            result = read_period_events(journal, ["2026-08-23", "2026-08-24"])

            self.assertEqual(len(result["recent"]), 2)
            self.assertEqual(result["recent"][0]["app"], "Code")
            self.assertEqual(result["recent"][1]["app"], "Chrome")


class HasEvidenceForHourTests(unittest.TestCase):
    def test_false_when_nothing_exists_for_the_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            self.assertFalse(has_evidence_for_hour(journal, "2026-08-23", 9))

    def test_true_when_a_jsonl_event_exists_for_the_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            (raw / "activity-2026-08-23.jsonl").write_text(
                json.dumps({"source": "foreground-window", "process": "Code", "localTimestamp": "2026-08-23T09:15:00+03:30", "active": True}) + "\n",
                encoding="utf-8",
            )
            self.assertTrue(has_evidence_for_hour(journal, "2026-08-23", 9))
            self.assertFalse(has_evidence_for_hour(journal, "2026-08-23", 10))

    def test_true_when_only_a_screenshot_exists_for_the_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            screenshots = journal / "screenshots" / "2026-08-23"
            screenshots.mkdir(parents=True)
            (screenshots / "screen-09-05-16-374.jpg").write_bytes(b"")

            self.assertTrue(has_evidence_for_hour(journal, "2026-08-23", 9))
            self.assertFalse(has_evidence_for_hour(journal, "2026-08-23", 14))


class WeekDatesTests(unittest.TestCase):
    def test_returns_monday_through_the_given_date(self):
        year, week, dates = week_dates("2026-08-27")
        self.assertEqual(dates, ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"])
        self.assertEqual((year, week), (2026, 35))


class RenderPeriodDocumentTests(unittest.TestCase):
    def test_produces_daily_matching_sections(self):
        narrative = {
            "summary": "Worked on the journal pipeline.",
            "timeline": [{"time": "09:15", "activity": "Started coding"}],
            "patterns": ["Steady focus on one file"],
            "next_actions": ["Write tests"],
            "confidence": 0.8,
        }
        result = render_period_document("Hourly journal — 2026-08-23 09:00", narrative)

        self.assertTrue(result.startswith("# Hourly journal — 2026-08-23 09:00\n\nWorked on the journal pipeline.\n"))
        self.assertIn("### Timeline", result)
        self.assertIn("- 09:15 — Started coding", result)
        self.assertIn("### Patterns", result)
        self.assertIn("### Next actions", result)
        self.assertIn("_LLM confidence: 0.8_", result)
        self.assertNotIn("### Accomplishments", result)
        self.assertNotIn("### Blockers", result)

    def test_omits_empty_sections(self):
        narrative = {"summary": "Quiet hour.", "confidence": 0.5}
        result = render_period_document("Hourly journal — 2026-08-23 03:00", narrative)

        self.assertNotIn("### Timeline", result)
        self.assertNotIn("### Patterns", result)
        self.assertNotIn("### Next actions", result)


class CallModelTests(unittest.TestCase):
    def test_uses_the_given_prompt_and_parses_the_response(self):
        from unittest import mock

        provider = {"name": "test"}
        evidence_dict = {"sessions": [], "recent": []}
        canned = '{"summary": "ok", "confidence": 0.9}'
        with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=canned) as mocked:
            result = call_model(provider, evidence_dict, HOURLY_PROMPT)

        self.assertEqual(result["summary"], "ok")
        mocked.assert_called_once()
        messages = mocked.call_args.args[1]
        self.assertEqual(messages[0]["content"], HOURLY_PROMPT)

    def test_weekly_prompt_is_distinct_from_hourly(self):
        self.assertNotEqual(HOURLY_PROMPT, WEEKLY_PROMPT)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthesize_period.py -v`
Expected: FAIL — `src.analysis.synthesize_period` does not exist yet.

- [ ] **Step 3: Create `synthesize_period.py` with the primitives**

Create `src/analysis/synthesize_period.py`:

```python
#!/usr/bin/env python3
"""Synthesize hourly and weekly narrative journals from local activity evidence."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
from typing import Callable

from src.analysis.narrative import compact_event, compact_session, event_stamp, fit_evidence, parse_model_json
from src.analysis.sessionize import detect_sessions
from src.providers.model_client import call_chat_completions


HOURLY_PROMPT = """You are writing a factual, detailed personal activity journal entry for ONE HOUR of observed computer events.
Return only valid JSON with this shape:
{
  "summary": "one or two concise factual sentences describing this hour",
  "timeline": [{"time": "HH:MM", "activity": "what was observed"}],
  "patterns": ["useful observed patterns within this hour"],
  "next_actions": ["reasonable next actions grounded in evidence, if any"],
  "confidence": 0.0
}
Be specific and fine-grained — this is a single hour, so capture the actual sequence of what happened, not a vague summary. Do not invent intent, accomplishments, people, conversations, or conclusions. Mark uncertain interpretations through a lower confidence value. Keep private message content summarized rather than reproduced."""

WEEKLY_PROMPT = """You are writing a factual, general personal activity journal entry summarizing ONE WEEK of observed computer events.
Return only valid JSON with this shape:
{
  "summary": "one concise factual paragraph covering the week as a whole",
  "timeline": [{"time": "HH:MM", "activity": "a few of the week's most significant moments only, not an hour-by-hour recap"}],
  "patterns": ["broad patterns observed across the week"],
  "next_actions": ["reasonable next actions grounded in evidence, if any"],
  "confidence": 0.0
}
Stay general — cover fewer, broader points rather than every detail; this is a week-level summary, not a merged hourly log. Do not invent intent, accomplishments, people, conversations, or conclusions. Mark uncertain interpretations through a lower confidence value. Keep private message content summarized rather than reproduced."""

_SCREENSHOT_FILENAME_PATTERN = re.compile(r"^screen-(\d{2})-\d{2}-\d{2}-\d+\.jpg$")


def _event_hour(event: dict) -> int | None:
    value = event_stamp(event)
    if not isinstance(value, str) or len(value) < 13:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).hour
    except ValueError:
        return None


def read_period_events(
    journal_root: pathlib.Path,
    dates: list[str],
    hour: int | None = None,
    compact: Callable[[dict], dict | None] = compact_event,
    limit: int = 1000,
) -> dict:
    raw_events: list[dict] = []
    compacted: list[dict] = []
    for date in dates:
        for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
            path = journal_root / "raw" / filename
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if hour is not None and _event_hour(record) != hour:
                    continue
                raw_events.append(record)
                event = compact(record)
                if event:
                    compacted.append(event)
    sessions = [compact_session(session) for session in detect_sessions(raw_events)]
    return {"sessions": sessions, "recent": compacted[-limit:]}


def has_evidence_for_hour(journal_root: pathlib.Path, date: str, hour: int) -> bool:
    for filename in (f"activity-{date}.jsonl", f"content-{date}.jsonl", f"visual-{date}.jsonl"):
        path = journal_root / "raw" / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _event_hour(record) == hour:
                return True
    screenshot_dir = journal_root / "screenshots" / date
    if screenshot_dir.exists():
        for path in screenshot_dir.glob("screen-*.jpg"):
            match = _SCREENSHOT_FILENAME_PATTERN.match(path.name)
            if match and int(match.group(1)) == hour:
                return True
    return False


def week_dates(date: str) -> tuple[int, int, list[str]]:
    parsed = dt.date.fromisoformat(date)
    year, week, weekday = parsed.isocalendar()
    monday = parsed - dt.timedelta(days=weekday - 1)
    dates = []
    day = monday
    while day <= parsed:
        dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    return year, week, dates


def render_period_document(title: str, narrative: dict) -> str:
    summary = str(narrative.get("summary", "No narrative summary returned.")).strip()
    lines = [f"# {title}", "", summary, ""]
    for section_title, key in (("Timeline", "timeline"), ("Patterns", "patterns"), ("Next actions", "next_actions")):
        values = narrative.get(key) or []
        if not values:
            continue
        lines.extend([f"### {section_title}", ""])
        for value in values:
            if isinstance(value, dict):
                lines.append(f"- {value.get('time', '')} — {value.get('activity', '')}".strip(" —"))
            else:
                lines.append(f"- {value}")
        lines.append("")
    lines.append(f"_LLM confidence: {narrative.get('confidence', 'unknown')}_")
    return "\n".join(lines).rstrip() + "\n"


def call_model(provider: dict, evidence_dict: dict, prompt: str, max_chars: int = 6000) -> dict:
    sessions, recent, evidence = fit_evidence(evidence_dict["sessions"], evidence_dict["recent"], max_chars)
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": f"Observed events:\n{evidence}"}]
    content = call_chat_completions(provider, messages, temperature=0.2)
    return parse_model_json(content)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesize_period.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/analysis/synthesize_period.py tests/test_synthesize_period.py
git commit -m "feat(analysis): add hourly and weekly narrative synthesis primitives"
```

---

### Task 2: Queue-backed retry and CLI entry point

**Files:**
- Modify: `src/analysis/synthesize_period.py`
- Test: `tests/test_synthesize_period.py`

**Interfaces:**
- Consumes: everything from Task 1 in the same file, plus `src.infra.processing_queue.FileJobQueue` (already exists — `enqueue(kind, payload, job_id=None)`, `claim(kind=None, exclude_ids=None)`, `complete(job_id, result)`, `fail(job_id, error, max_attempts=3, retry_delay_seconds=30)`), `src.infra.heartbeat.write_heartbeat` (already exists), `src.providers.model_client.resolve_provider`/`ProviderError` (already exist).
- Produces: `synthesize_hour(provider, journal_root, date, hour) -> dict` (raises on failure, returns `{"path": str}` on success), `synthesize_week(provider, journal_root, date) -> dict` (raises on failure, returns `{"path": str, "year": int, "week": int}`), CLI `main()` — consumed by Task 3's `run_hourly.py` wiring via subprocess, not by import.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_synthesize_period.py` (new imports at the top — add `sys` and `mock` alongside the existing ones, and extend the `from src.analysis.synthesize_period import (...)` line with `main, synthesize_hour, synthesize_week`):

```python
import sys
from unittest import mock

from src.analysis.synthesize_period import (
    HOURLY_PROMPT,
    WEEKLY_PROMPT,
    call_model,
    has_evidence_for_hour,
    main,
    read_period_events,
    render_period_document,
    synthesize_hour,
    synthesize_week,
    week_dates,
)
```

Then add these test classes:

```python
class SynthesizeHourTests(unittest.TestCase):
    def test_writes_the_rendered_document(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            (raw / "activity-2026-08-23.jsonl").write_text(
                json.dumps({"source": "foreground-window", "process": "Code", "localTimestamp": "2026-08-23T09:15:00+03:30", "active": True}) + "\n",
                encoding="utf-8",
            )
            canned = json.dumps({"summary": "Coded for an hour.", "confidence": 0.7})
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=canned):
                result = synthesize_hour({"name": "test"}, journal, "2026-08-23", 9)

            path = journal / "hourly" / "2026-08-23" / "09.md"
            self.assertEqual(result["path"], str(path))
            self.assertIn("Coded for an hour.", path.read_text(encoding="utf-8"))

    def test_raises_when_the_model_call_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value="not json"):
                with self.assertRaises(json.JSONDecodeError):
                    synthesize_hour({"name": "test"}, journal, "2026-08-23", 9)


class SynthesizeWeekTests(unittest.TestCase):
    def test_writes_the_rendered_document(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            canned = json.dumps({"summary": "Steady week.", "confidence": 0.6})
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=canned):
                result = synthesize_week({"name": "test"}, journal, "2026-08-27")

            year, week, _ = week_dates("2026-08-27")
            path = journal / "weekly" / f"{year}-W{week:02d}.md"
            self.assertEqual(result["path"], str(path))
            self.assertIn("Steady week.", path.read_text(encoding="utf-8"))


class MainTests(unittest.TestCase):
    def _run(self, journal_root: Path, config_path: Path, period: str, date: str) -> int:
        old_argv = sys.argv
        sys.argv = [
            "synthesize_period",
            "--journal-root", str(journal_root),
            "--config", str(config_path),
            "--period", period,
            "--date", date,
        ]
        try:
            return main()
        finally:
            sys.argv = old_argv

    def _config(self, directory: Path, period: str) -> Path:
        stage_key = "hourlySynthesis" if period == "hourly" else "weeklySynthesis"
        config_path = directory / "settings.json"
        config_path.write_text(json.dumps({
            stage_key: {"enabled": True, "activeProvider": "test-provider", "maxAttempts": 5, "retryDelaySeconds": 60},
            "providers": {"test-provider": {"endpoint": "http://x", "model": "m"}},
        }), encoding="utf-8")
        return config_path

    def test_zero_evidence_hour_writes_nothing_and_never_calls_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            config_path = self._config(root, "hourly")
            fixed_now = dt.datetime(2026, 8, 23, 9, 30, 0)
            with mock.patch("src.analysis.synthesize_period.dt") as mocked_dt:
                mocked_dt.datetime.now.return_value = fixed_now
                mocked_dt.date.today.return_value = fixed_now.date()
                mocked_dt.date.fromisoformat = dt.date.fromisoformat
                mocked_dt.datetime.fromisoformat = dt.datetime.fromisoformat
                mocked_dt.timedelta = dt.timedelta
                with mock.patch("src.analysis.synthesize_period.call_chat_completions") as mocked:
                    exit_code = self._run(journal, config_path, "hourly", "2026-08-23")

            self.assertEqual(exit_code, 0)
            mocked.assert_not_called()
            self.assertFalse((journal / "hourly").exists())

    def test_hour_with_a_pending_screenshot_calls_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            screenshots = journal / "screenshots" / "2026-08-23"
            screenshots.mkdir(parents=True)
            (screenshots / "screen-09-05-16-374.jpg").write_bytes(b"")
            config_path = self._config(root, "hourly")
            fixed_now = dt.datetime(2026, 8, 23, 9, 30, 0)
            canned = json.dumps({"summary": "Screenshot-only hour.", "confidence": 0.4})
            with mock.patch("src.analysis.synthesize_period.dt") as mocked_dt:
                mocked_dt.datetime.now.return_value = fixed_now
                mocked_dt.date.today.return_value = fixed_now.date()
                mocked_dt.date.fromisoformat = dt.date.fromisoformat
                mocked_dt.datetime.fromisoformat = dt.datetime.fromisoformat
                mocked_dt.timedelta = dt.timedelta
                with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=canned):
                    exit_code = self._run(journal, config_path, "hourly", "2026-08-23")

            self.assertEqual(exit_code, 0)
            self.assertTrue((journal / "hourly" / "2026-08-23" / "09.md").exists())

    def test_failed_hour_is_queued_and_main_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            raw = journal / "raw"
            raw.mkdir(parents=True)
            (raw / "activity-2026-08-23.jsonl").write_text(
                json.dumps({"source": "foreground-window", "process": "Code", "localTimestamp": "2026-08-23T09:15:00+03:30", "active": True}) + "\n",
                encoding="utf-8",
            )
            config_path = self._config(root, "hourly")
            fixed_now = dt.datetime(2026, 8, 23, 9, 30, 0)
            with mock.patch("src.analysis.synthesize_period.dt") as mocked_dt:
                mocked_dt.datetime.now.return_value = fixed_now
                mocked_dt.date.today.return_value = fixed_now.date()
                mocked_dt.date.fromisoformat = dt.date.fromisoformat
                mocked_dt.datetime.fromisoformat = dt.datetime.fromisoformat
                mocked_dt.timedelta = dt.timedelta
                with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value="not json"):
                    exit_code = self._run(journal, config_path, "hourly", "2026-08-23")

            self.assertEqual(exit_code, 0)
            queued = list((journal / "queue-period" / "pending").glob("*.json"))
            self.assertEqual(len(queued), 1)
            self.assertFalse((journal / "hourly" / "2026-08-23" / "09.md").exists())

    def test_a_due_retry_is_attempted_before_the_current_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            raw = journal / "raw"
            raw.mkdir(parents=True)
            (raw / "activity-2026-08-23.jsonl").write_text(
                "\n".join(json.dumps({"source": "foreground-window", "process": "Code", "localTimestamp": f"2026-08-23T{h:02d}:15:00+03:30", "active": True}) for h in (8, 9)) + "\n",
                encoding="utf-8",
            )
            config_path = self._config(root, "hourly")
            from src.infra.processing_queue import FileJobQueue
            queue = FileJobQueue(journal / "queue-period")
            queue.enqueue("hourly", {"date": "2026-08-23", "hour": 8}, job_id="hourly:2026-08-23:08")
            fixed_now = dt.datetime(2026, 8, 23, 9, 30, 0)
            canned = json.dumps({"summary": "ok", "confidence": 0.5})
            with mock.patch("src.analysis.synthesize_period.dt") as mocked_dt:
                mocked_dt.datetime.now.return_value = fixed_now
                mocked_dt.date.today.return_value = fixed_now.date()
                mocked_dt.date.fromisoformat = dt.date.fromisoformat
                mocked_dt.datetime.fromisoformat = dt.datetime.fromisoformat
                mocked_dt.timedelta = dt.timedelta
                with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=canned) as mocked:
                    exit_code = self._run(journal, config_path, "hourly", "2026-08-23")

            self.assertEqual(exit_code, 0)
            self.assertEqual(mocked.call_count, 2)
            self.assertTrue((journal / "hourly" / "2026-08-23" / "08.md").exists())
            self.assertTrue((journal / "hourly" / "2026-08-23" / "09.md").exists())

    def test_disabled_stage_writes_nothing_and_never_calls_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({"hourlySynthesis": {"enabled": False}}), encoding="utf-8")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions") as mocked:
                exit_code = self._run(journal, config_path, "hourly", "2026-08-23")

            self.assertEqual(exit_code, 0)
            mocked.assert_not_called()

    def test_weekly_period_writes_to_the_weekly_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            config_path = self._config(root, "weekly")
            canned = json.dumps({"summary": "Weekly rollup.", "confidence": 0.6})
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=canned):
                exit_code = self._run(journal, config_path, "weekly", "2026-08-27")

            year, week, _ = week_dates("2026-08-27")
            self.assertEqual(exit_code, 0)
            self.assertTrue((journal / "weekly" / f"{year}-W{week:02d}.md").exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthesize_period.py -v`
Expected: FAIL — `synthesize_hour`, `synthesize_week`, `main` don't exist yet.

- [ ] **Step 3: Add the queue-backed synthesis functions and CLI**

Append to `src/analysis/synthesize_period.py` (after `call_model`, replacing the file's absence of a `main`/CLI section). First, add these imports to the top of the file, alongside the existing ones:

```python
import argparse

from src.infra.heartbeat import write_heartbeat
from src.infra.processing_queue import FileJobQueue
from src.providers.model_client import ProviderError, resolve_provider
```

Then append:

```python
def synthesize_hour(provider: dict, journal_root: pathlib.Path, date: str, hour: int) -> dict:
    evidence = read_period_events(journal_root, [date], hour=hour)
    narrative = call_model(provider, evidence, HOURLY_PROMPT)
    path = journal_root / "hourly" / date / f"{hour:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_period_document(f"Hourly journal — {date} {hour:02d}:00", narrative), encoding="utf-8")
    return {"path": str(path)}


def synthesize_week(provider: dict, journal_root: pathlib.Path, date: str) -> dict:
    year, week, dates = week_dates(date)
    evidence = read_period_events(journal_root, dates)
    narrative = call_model(provider, evidence, WEEKLY_PROMPT)
    path = journal_root / "weekly" / f"{year}-W{week:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_period_document(f"Weekly journal — {year}-W{week:02d}", narrative), encoding="utf-8")
    return {"path": str(path), "year": year, "week": week}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--period", required=True, choices=("hourly", "weekly"))
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal = args.journal_root
    config = json.loads(args.config.read_text(encoding="utf-8"))
    stage_key = "hourlySynthesis" if args.period == "hourly" else "weeklySynthesis"
    stage_config = config.get(stage_key) or {}
    heartbeat_name = f"{args.period}-synthesis"

    if not stage_config.get("enabled", True):
        print(json.dumps({"period": args.period, "status": "disabled"}))
        return 0

    try:
        provider = resolve_provider(config, stage_key)
    except ProviderError as error:
        write_heartbeat(journal, heartbeat_name, "failed", error_message=str(error))
        print(f"{args.period} synthesis failed: {error}")
        return 0

    max_attempts = int(stage_config.get("maxAttempts", 5))
    retry_delay_seconds = int(stage_config.get("retryDelaySeconds", 60))
    queue = FileJobQueue(journal / "queue-period")

    results: list[dict] = []
    attempted: set[str] = set()
    while True:
        job = queue.claim(kind=args.period, exclude_ids=attempted)
        if job is None:
            break
        attempted.add(job["id"])
        payload = job["payload"]
        try:
            if args.period == "hourly":
                result = synthesize_hour(provider, journal, payload["date"], payload["hour"])
            else:
                result = synthesize_week(provider, journal, payload["date"])
            queue.complete(job["id"], result)
            results.append({"status": "complete", **result})
        except (OSError, ValueError, KeyError, json.JSONDecodeError, ProviderError) as error:
            outcome = queue.fail(job["id"], str(error), max_attempts=max_attempts, retry_delay_seconds=retry_delay_seconds)
            results.append({"status": outcome["status"], "error": str(error)})

    if args.period == "hourly":
        now = dt.datetime.now()
        hour = now.hour
        job_id = f"hourly:{args.date}:{hour:02d}"
        if queue.find(job_id) is None:
            if not has_evidence_for_hour(journal, args.date, hour):
                results.append({"status": "no-evidence", "date": args.date, "hour": hour})
            else:
                try:
                    result = synthesize_hour(provider, journal, args.date, hour)
                    results.append({"status": "complete", **result})
                except (OSError, ValueError, KeyError, json.JSONDecodeError, ProviderError) as error:
                    queue.enqueue("hourly", {"date": args.date, "hour": hour}, job_id=job_id)
                    results.append({"status": "failed", "error": str(error)})
    else:
        year, week, _ = week_dates(args.date)
        job_id = f"weekly:{year}-W{week:02d}"
        if queue.find(job_id) is None:
            try:
                result = synthesize_week(provider, journal, args.date)
                results.append({"status": "complete", **result})
            except (OSError, ValueError, KeyError, json.JSONDecodeError, ProviderError) as error:
                queue.enqueue("weekly", {"date": args.date}, job_id=job_id)
                results.append({"status": "failed", "error": str(error)})

    print(json.dumps({"period": args.period, "results": results}, ensure_ascii=False))
    failed = [item for item in results if item["status"] == "failed"]
    completed = [item for item in results if item["status"] == "complete"]
    if failed:
        write_heartbeat(journal, heartbeat_name, "failed", items_processed=len(completed), error_message=failed[-1]["error"])
    else:
        write_heartbeat(journal, heartbeat_name, "success", items_processed=len(completed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesize_period.py -v`
Expected: all PASS. Note: the tests that patch `src.analysis.synthesize_period.dt` do so to pin "now" for `datetime.now()`/`date.today()` while leaving `date.fromisoformat`, `datetime.fromisoformat`, and `timedelta` as real implementations (assigned through from the real `dt` module) — this is necessary because `main()`, `week_dates()`, and `_event_hour()` all call real `dt.*` functions that must keep working during the same test.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/analysis/synthesize_period.py tests/test_synthesize_period.py
git commit -m "feat(analysis): queue failed period synthesis for retry"
```

---

### Task 3: Wire into the hourly job and document the config

**Files:**
- Modify: `src/orchestration/run_hourly.py`
- Modify: `config/settings.example.json`
- Test: `tests/test_run_hourly.py` (new file)

**Interfaces:**
- Consumes: `src.analysis.synthesize_period`'s CLI (Task 2), invoked via `subprocess.run` exactly like the deleted `build_journals` call was.
- Produces: nothing consumed elsewhere — this is the orchestration wiring.

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_hourly.py`, mirroring `tests/test_daily_summary.py`'s exact mocking idiom:

```python
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.orchestration.run_hourly import main


class RunHourlyWiringTests(unittest.TestCase):
    def _invoke_main(self, journal_root: Path, config_path: Path, date: str):
        mock_result = MagicMock()
        mock_result.returncode = 0
        old_argv = sys.argv
        sys.argv = [
            "run_hourly",
            "--journal-root", str(journal_root),
            "--config", str(config_path),
            "--date", date,
        ]
        try:
            with patch(
                "src.orchestration.run_hourly.subprocess.run",
                return_value=mock_result,
            ) as mock_run:
                exit_code = main()
        finally:
            sys.argv = old_argv
        return exit_code, mock_run

    def _calls_containing(self, mock_run, needle: str):
        return [call for call in mock_run.call_args_list if needle in call.args[0]]

    def test_build_journals_is_no_longer_invoked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text("{}", encoding="utf-8")

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-30")

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(self._calls_containing(mock_run, "src.analysis.build_journals")), 0)

    def test_synthesize_period_is_invoked_for_both_hourly_and_weekly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text("{}", encoding="utf-8")

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-30")

            self.assertEqual(exit_code, 0)
            period_calls = self._calls_containing(mock_run, "src.analysis.synthesize_period")
            self.assertEqual(len(period_calls), 2)
            periods = {call.args[0][call.args[0].index("--period") + 1] for call in period_calls}
            self.assertEqual(periods, {"hourly", "weekly"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_hourly.py -v`
Expected: FAIL — `build_journals` is still invoked, `synthesize_period` is not.

- [ ] **Step 3: Rewire `run_hourly.py`**

In `src/orchestration/run_hourly.py`, find:

```python
    steps = [
        [sys.executable, "-m", "src.analysis.build_journals", "--journal-root", str(args.journal_root), "--date", args.date],
        [sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(args.journal_root), "--date", args.date],
        [sys.executable, "-m", "src.analysis.synthesize_journal", "--journal-root", str(args.journal_root), "--config", str(args.config), "--date", args.date],
    ]
```

Replace with:

```python
    steps = [
        [sys.executable, "-m", "src.analysis.synthesize_period", "--journal-root", str(args.journal_root), "--config", str(args.config), "--period", "hourly", "--date", args.date],
        [sys.executable, "-m", "src.analysis.synthesize_period", "--journal-root", str(args.journal_root), "--config", str(args.config), "--period", "weekly", "--date", args.date],
        [sys.executable, "-m", "src.analysis.build_llm_context", "--journal-root", str(args.journal_root), "--date", args.date],
        [sys.executable, "-m", "src.analysis.synthesize_journal", "--journal-root", str(args.journal_root), "--config", str(args.config), "--date", args.date],
    ]
```

- [ ] **Step 4: Document the new config stages and add Groq key rotation for text**

In `config/settings.example.json`, add two new keys as siblings of `journalSynthesis`:

```json
  "journalSynthesis": {
    "enabled": true,
    "activeProvider": "local-text"
  },
  "hourlySynthesis": {
    "enabled": true,
    "activeProvider": "cloud-text-groq",
    "maxAttempts": 5,
    "retryDelaySeconds": 60
  },
  "weeklySynthesis": {
    "enabled": true,
    "activeProvider": "cloud-text-groq",
    "maxAttempts": 5,
    "retryDelaySeconds": 60
  },
```

And change `cloud-text-groq`'s `apiKeyEnv` from a single string to a rotation list, matching `cloud-vision-groq`'s existing pattern. Find:

```json
    "cloud-text-groq": {
      "endpoint": "https://api.groq.com/openai/v1/chat/completions",
      "model": "openai/gpt-oss-120b",
      "apiKeyEnv": "GROQ_API_KEY",
      "proxy": "http://127.0.0.1:10808"
    },
```

Replace with:

```json
    "cloud-text-groq": {
      "endpoint": "https://api.groq.com/openai/v1/chat/completions",
      "model": "openai/gpt-oss-120b",
      "apiKeyEnv": ["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"],
      "proxy": "http://127.0.0.1:10808"
    },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_hourly.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/orchestration/run_hourly.py config/settings.example.json tests/test_run_hourly.py
git commit -m "feat(orchestration): run hourly and weekly narrative synthesis, rotate Groq text keys"
```

---

### Task 4: Delete the deterministic renderer and document

**Files:**
- Delete: `src/analysis/build_journals.py`, `src/analysis/journalize.py`, `tests/test_journalize.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Confirm nothing else references the files being deleted**

Run: `grep -rn "journalize\|build_journals" --include="*.py" src/ tests/`
Expected: only matches inside `src/analysis/journalize.py`, `src/analysis/build_journals.py`, and `tests/test_journalize.py` themselves. If anything else matches, stop and report it — do not delete until this is confirmed clean.

- [ ] **Step 2: Delete the files**

```bash
git rm src/analysis/build_journals.py src/analysis/journalize.py tests/test_journalize.py
```

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass — no import errors, no missing-module failures.

- [ ] **Step 4: Update the README**

In `README.md`, find the Architecture section's diagram:

```text
Screenshot → vision model  → visual activity JSON   (Journal/raw/visual-DATE.jsonl)
All events → text model    → daily journal narrative (Journal/daily/DATE.md, "LLM narrative" section)
```

Replace with:

```text
Screenshot → vision model  → visual activity JSON        (Journal/raw/visual-DATE.jsonl)
All events → text model    → daily journal narrative      (Journal/daily/DATE.md, "LLM narrative" section)
All events → text model    → hourly/weekly journal narrative (Journal/hourly/DATE/HH.md, Journal/weekly/YYYY-Www.md)
```

In the `## Pipeline` section, find:

```text
Every hourlyBuild.intervalSeconds (default 1h)
  |- analysis/build_journals.py     -> deterministic hourly + weekly Markdown (no model call)
  |- analysis/build_llm_context.py  -> Journal/llm-context/latest.md (raw evidence feed for an LLM assistant)
  `- analysis/synthesize_journal.py -> text model -> Journal/daily/DATE.md ("LLM narrative" section)
```

Replace with:

```text
Every hourlyBuild.intervalSeconds (default 1h)
  |- analysis/synthesize_period.py  -> text model -> Journal/hourly/DATE/HH.md and Journal/weekly/YYYY-Www.md
  |                                    (an hour with zero evidence — no events, no screenshot — is skipped, not synthesized;
  |                                    a failed call is queued in Journal/queue-period/ and retried on the next run)
  |- analysis/build_llm_context.py  -> Journal/llm-context/latest.md (raw evidence feed for an LLM assistant)
  `- analysis/synthesize_journal.py -> text model -> Journal/daily/DATE.md ("LLM narrative" section)
```

In the "### Durable retry queue" section, find the closing sentence:

```text
After `maxAttempts` failures a job moves to `Journal/queue/failed/` (dead letter) rather than retrying forever. `python -m src.ops.dashboard` exposes queue depth per state.
```

Replace with:

```text
After `maxAttempts` failures a job moves to `Journal/queue/failed/` (dead letter) rather than retrying forever. `python -m src.ops.dashboard` exposes queue depth per state. Hourly and weekly narrative synthesis use the same pattern against a separate queue root, `Journal/queue-period/` — a failed LLM call is queued and retried on the next hourly run rather than lost.
```

In the `## Repository layout` section's `analysis/` block, find:

```text
    analyze_screenshots.py  screenshots -> vision model -> visual-DATE.jsonl
    synthesize_journal.py   events -> text model -> daily narrative
    journalize.py            deterministic Markdown rendering (no model call)
    sessionize.py            activity-session classification (no model call)
    build_journals.py        hourly/weekly Markdown (no model call)
    build_llm_context.py     llm-context/latest.md, raw evidence for an LLM assistant
```

Replace with:

```text
    analyze_screenshots.py  screenshots -> vision model -> visual-DATE.jsonl
    synthesize_journal.py   events -> text model -> daily narrative
    synthesize_period.py    events -> text model -> hourly + weekly narrative, queue-backed retry
    sessionize.py            activity-session classification (no model call)
    build_llm_context.py     llm-context/latest.md, raw evidence for an LLM assistant
```

- [ ] **Step 5: Run the full suite once more**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: remove build_journals and journalize references, document period synthesis"
```

---

## Self-Review

**Spec coverage:** narrative-only format matching daily's exact sections (Task 1's `render_period_document`) ✓; hourly cadence for weekly too (Task 3's `run_hourly.py` wiring runs both every hour) ✓; queue-retry on LLM failure via `FileJobQueue` (Task 2) ✓; zero-evidence skip including the screenshot-presence check (Task 1's `has_evidence_for_hour`, Task 2's `main()` gating) ✓; `build_journals.py`/`journalize.py` deletion confirmed safe and executed (Task 4) ✓; `cloud-text-groq` 3-key rotation (Task 3) ✓; README updated (Task 4) ✓.

**Placeholder scan:** no TBD/TODO; every step has real, complete code.

**Type consistency:** `read_period_events`'s signature (`journal_root, dates, hour=None, compact=, limit=`) matches exactly between its Task 1 definition and every Task 2 call site (`synthesize_hour` passes `[date], hour=hour`; `synthesize_week` passes `dates` with no `hour`). `has_evidence_for_hour(journal_root, date, hour)`'s signature matches its one call site in `main()`. `synthesize_hour`/`synthesize_week` both raise on failure and return a dict with `"path"` on success — `main()`'s two call sites (queue-drain loop and current-period attempt) both handle this via the same `try/except` shape. `week_dates(date) -> (year, week, dates)` return shape is used consistently by `synthesize_week`, `main()`'s weekly job-id construction, and the tests.
