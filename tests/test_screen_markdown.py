import json
import tempfile
import unittest
from pathlib import Path

from src.analysis.screen_markdown import (
    load_analyses,
    reconcile_duplicates,
    render_screen_markdown,
    screen_path,
    write_screen_markdown,
)

IMAGE = Path("/j/screenshots/2026-09-26/screen-10-21-15-521.jpg")
ANALYSIS = {
    "summary": "Viewing Kibana dashboards.",
    "applications": "Elastic Kibana, Google Chrome",
    "projects": "kassa-log, nginx-moadian",
    "activity_type": "browsing",
    "observations": ["A 12-hour chart is visible."],
    "screen_details": ["The data view selector lists declaration-app-log."],
}


class RenderTests(unittest.TestCase):
    def test_renders_details_before_observations_and_metadata(self):
        text = render_screen_markdown(IMAGE, ANALYSIS)

        self.assertTrue(text.startswith("# Screen — 2026-09-26 10:21:15\n\nViewing Kibana dashboards.\n"))
        self.assertIn("### On screen", text)
        self.assertLess(text.index("- The data view selector"), text.index("- A 12-hour chart"))
        self.assertIn("**Apps:** Elastic Kibana, Google Chrome", text)
        self.assertIn("**Projects:** kassa-log, nginx-moadian", text)
        self.assertIn("**Activity:** browsing", text)

    def test_is_human_readable_with_no_confidence_or_iso_timestamps(self):
        text = render_screen_markdown(IMAGE, {**ANALYSIS, "confidence": 0.9})

        self.assertNotIn("confidence", text.lower())
        self.assertNotIn("+00:00", text)
        self.assertNotIn("T10:", text)
        self.assertNotIn("`", text)

    def test_duplicate_gets_an_unchanged_line(self):
        text = render_screen_markdown(IMAGE, ANALYSIS, unchanged_since="10:19:15")

        self.assertIn("Unchanged since 10:19:15.", text)
        self.assertIn("### On screen", text)

    def test_list_valued_apps_and_string_valued_details_are_tolerated(self):
        analysis = {"summary": "s", "applications": ["Code", "Terminal"], "projects": [], "observations": "One observation", "screen_details": "One detail"}

        text = render_screen_markdown(IMAGE, analysis)

        self.assertIn("**Apps:** Code, Terminal", text)
        self.assertNotIn("**Projects:**", text)
        self.assertIn("- One detail", text)
        self.assertIn("- One observation", text)

    def test_unrecognised_filename_does_not_crash(self):
        image = Path("/j/screenshots/2026-09-26/odd-name.jpg")

        text = render_screen_markdown(image, ANALYSIS)
        path = screen_path(Path("/j"), image)

        self.assertTrue(text.startswith("# Screen — 2026-09-26 odd-name\n"))
        self.assertEqual(path, Path("/j/screens/2026-09-26/unknown/odd-name.md"))


class WriteTests(unittest.TestCase):
    def test_writes_under_screens_date_hour_and_overwrites_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)

            first = write_screen_markdown(journal, IMAGE, ANALYSIS)
            content = first.read_text(encoding="utf-8")
            second = write_screen_markdown(journal, IMAGE, ANALYSIS)

            self.assertEqual(first, journal / "screens" / "2026-09-26" / "10" / "10-21-15-521.md")
            self.assertEqual(first, second)
            self.assertEqual(content, second.read_text(encoding="utf-8"))


def _write_visual(journal: Path, date: str, entries: list[tuple[Path, dict]]) -> None:
    raw = journal / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"source": "screenshot-vision", "screenshot": str(image), "analysis": analysis}) for image, analysis in entries]
    (raw / f"visual-{date}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


class ReconcileDuplicatesTests(unittest.TestCase):
    def setUp(self):
        self.kept = Path("/j/screenshots/2026-09-26/screen-10-19-15-000.jpg")
        self.dup = Path("/j/screenshots/2026-09-26/screen-10-20-15-000.jpg")

    def test_duplicate_of_an_analysed_screenshot_gets_an_unchanged_file(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _write_visual(journal, "2026-09-26", [(self.kept, ANALYSIS)])

            written = reconcile_duplicates(journal, "2026-09-26", {self.dup: self.kept})

            target = screen_path(journal, self.dup)
            self.assertEqual(written, [target])
            text = target.read_text(encoding="utf-8")
            self.assertIn("# Screen — 2026-09-26 10:20:15", text)
            self.assertIn("Unchanged since 10:19:15.", text)
            self.assertIn("### On screen", text)

    def test_waits_until_the_kept_screenshot_is_analysed_then_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)

            self.assertEqual(reconcile_duplicates(journal, "2026-09-26", {self.dup: self.kept}), [])
            self.assertFalse(screen_path(journal, self.dup).exists())

            _write_visual(journal, "2026-09-26", [(self.kept, ANALYSIS)])
            written = reconcile_duplicates(journal, "2026-09-26", {})

            self.assertEqual(written, [screen_path(journal, self.dup)])

    def test_existing_file_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _write_visual(journal, "2026-09-26", [(self.kept, ANALYSIS)])
            reconcile_duplicates(journal, "2026-09-26", {self.dup: self.kept})

            self.assertEqual(reconcile_duplicates(journal, "2026-09-26", {}), [])

    def test_load_analyses_maps_screenshot_to_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _write_visual(journal, "2026-09-26", [(self.kept, ANALYSIS)])

            self.assertEqual(load_analyses(journal, "2026-09-26"), {str(self.kept): ANALYSIS})
            self.assertEqual(load_analyses(journal, "2026-01-01"), {})


if __name__ == "__main__":
    unittest.main()
