import unittest

from src.analysis.synthesize_journal import parse_model_json, upsert_narrative


class SynthesisTests(unittest.TestCase):
    def test_parse_model_json_accepts_fenced_json(self):
        result = parse_model_json('```json\n{"summary":"Worked on Jarvis","confidence":0.9}\n```')
        self.assertEqual(result["summary"], "Worked on Jarvis")

    def test_upsert_narrative_replaces_existing_section(self):
        original = "# Daily Journal\n\n## Applications\n\n- PowerShell\n\n## LLM narrative\n\nOld text\n"
        updated = upsert_narrative(original, {"summary": "Worked on the journal pipeline", "confidence": 0.8})
        self.assertEqual(updated.count("## LLM narrative"), 1)
        self.assertIn("Worked on the journal pipeline", updated)
        self.assertNotIn("Old text", updated)

    def test_compact_session_produces_a_compact_dict(self):
        import datetime as dt

        from src.analysis.synthesize_journal import compact_session

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
        self.assertEqual(result["class"], "coding")
        self.assertEqual(result["apps"], ["Code", "WindowsTerminal"])
        self.assertNotIn("confidence", result)

    def test_read_events_returns_sessions_and_recent_events_separately(self):
        import datetime as dt
        import json
        import tempfile
        from pathlib import Path

        from src.analysis.synthesize_journal import read_events

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            raw = journal / "raw"
            raw.mkdir()
            events = [
                {"source": "foreground-window", "process": "Code", "timestamp": f"2026-08-23T{hour:02d}:00:00+00:00", "localTimestamp": f"2026-08-23T{hour:02d}:00:00+00:00", "active": True}
                for hour in range(9, 18)
            ]
            (raw / "activity-2026-08-23.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

            result = read_events(journal, "2026-08-23")

            self.assertIn("sessions", result)
            self.assertIn("recent", result)
            self.assertTrue(len(result["sessions"]) >= 1)
            first_hour = result["sessions"][0]["t"]
            expected_first_hour = dt.datetime.fromisoformat(events[0]["timestamp"]).astimezone().strftime("%H:%M")
            self.assertIn(expected_first_hour, first_hour)


if __name__ == "__main__":
    unittest.main()
