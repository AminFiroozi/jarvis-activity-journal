import json
import tempfile
import unittest
from pathlib import Path

from src.infra.processing_queue import FileJobQueue
from src.ops.migrate_screens import backfill, main


def _visual(journal: Path, date: str, image: Path, analysis: dict) -> None:
    raw = journal / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with (raw / f"visual-{date}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"source": "screenshot-vision", "screenshot": str(image), "analysis": analysis}) + "\n")


class BackfillTests(unittest.TestCase):
    def test_writes_a_file_per_analysed_screenshot_and_skips_existing_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            first = journal / "screenshots" / "2026-09-26" / "screen-10-21-15-521.jpg"
            second = journal / "screenshots" / "2026-09-25" / "screen-09-00-00-000.jpg"
            _visual(journal, "2026-09-26", first, {"summary": "Kibana", "observations": ["chart"]})
            _visual(journal, "2026-09-25", second, {"summary": "Editor"})

            self.assertEqual(backfill(journal), 2)
            self.assertEqual(backfill(journal), 0)
            self.assertIn("Kibana", (journal / "screens" / "2026-09-26" / "10" / "10-21-15-521.md").read_text(encoding="utf-8"))
            self.assertTrue((journal / "screens" / "2026-09-25" / "09" / "09-00-00-000.md").exists())

    def test_malformed_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "raw").mkdir()
            (journal / "raw" / "visual-2026-09-26.jsonl").write_text("not json\n{}\n", encoding="utf-8")

            self.assertEqual(backfill(journal), 0)


class MainTests(unittest.TestCase):
    def test_requeue_failed_flag_moves_vision_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            queue = FileJobQueue(journal / "queue")
            queue.enqueue("vision", {"screenshot": "a.jpg"}, job_id="a")
            queue.claim()
            queue.fail("a", "boom", max_attempts=1)

            exit_code = main(["--journal-root", str(journal), "--requeue-failed"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(queue.find("a")[0], "pending")


if __name__ == "__main__":
    unittest.main()
