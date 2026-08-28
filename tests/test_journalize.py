import unittest
import tempfile
from pathlib import Path

from src.analysis.journalize import render_journal, write_journal_documents


class JournalizeTests(unittest.TestCase):
    def test_renders_sessions_and_evidence_as_human_readable_text(self):
        markdown = render_journal(
            "Daily journal",
            [
                {"id": "e1", "observedAt": "2026-08-23T10:00:00+00:00", "kind": "foreground", "application": "Code"}
            ],
            [
                {
                    "id": "s1",
                    "startAt": "2026-08-23T10:00:00+00:00",
                    "endAt": "2026-08-23T10:30:00+00:00",
                    "classification": "coding",
                    "confidence": 0.9,
                    "apps": ["Code"],
                    "eventIds": ["e1"],
                }
            ],
        )

        self.assertIn("# Daily journal", markdown)
        self.assertIn("coding", markdown)
        self.assertIn("30m", markdown)
        self.assertIn("Code", markdown)
        self.assertNotIn("`e1`", markdown)
        self.assertNotIn("2026-08-23T10:00:00+00:00", markdown)

    def test_empty_journal_is_explicit_and_repeatable(self):
        first = render_journal("Empty", [], [])
        second = render_journal("Empty", [], [])

        self.assertEqual(first, second)
        self.assertIn("No activity evidence", first)

    def test_writes_hourly_daily_and_weekly_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_journal_documents(
                Path(directory),
                "2026-08-23",
                [{"id": "e1", "observedAt": "2026-08-23T10:00:00+00:00", "kind": "coding"}],
                [],
            )

            self.assertTrue((Path(directory) / "hourly/2026-08-23/10.md").is_file())
            self.assertTrue((Path(directory) / "daily/2026-08-23.md").is_file())
            self.assertTrue(any(path.name.startswith("2026-W") for path in paths))

    def test_screen_evidence_shows_detected_app_not_unknown(self):
        markdown = render_journal(
            "Daily journal",
            [
                {
                    "source": "screenshot-vision",
                    "timestamp": "2026-08-23T10:00:00+00:00",
                    "analysis": {"applications": ["Visual Studio Code"], "summary": "coding"},
                }
            ],
            [],
        )

        self.assertIn("Visual Studio Code", markdown)
        self.assertNotIn("unknown", markdown)

    def test_screen_evidence_collapses_runs_regardless_of_app_list_order(self):
        markdown = render_journal(
            "Daily journal",
            [
                {
                    "source": "screenshot-vision",
                    "timestamp": "2026-08-23T10:00:00+00:00",
                    "analysis": {"applications": ["Code", "Chrome"], "summary": "coding"},
                },
                {
                    "source": "screenshot-vision",
                    "timestamp": "2026-08-23T10:01:00+00:00",
                    "analysis": {"applications": ["Chrome", "Code"], "summary": "coding"},
                },
            ],
            [],
        )

        evidence_lines = [line for line in markdown.splitlines() if line.startswith("- ") and "screen" in line]
        self.assertEqual(len(evidence_lines), 1)
        self.assertIn("(2 samples)", evidence_lines[0])


if __name__ == "__main__":
    unittest.main()
