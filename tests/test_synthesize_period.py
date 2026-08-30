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
