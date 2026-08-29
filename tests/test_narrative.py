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
