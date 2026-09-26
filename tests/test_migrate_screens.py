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
            image = journal / "screenshots" / "2026-09-26" / "screen-10-00-00-000.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"x")
            queue.enqueue("vision", {"screenshot": str(image)}, job_id="a")
            queue.claim()
            queue.fail("a", "boom", max_attempts=1)

            exit_code = main(["--journal-root", str(journal), "--requeue-failed"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(queue.find("a")[0], "pending")


class MissingScreenshotTests(unittest.TestCase):
    def _queue_with_jobs(self, journal: Path):
        existing = journal / "screenshots" / "2026-09-26" / "screen-10-00-00-000.jpg"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"x")
        missing = journal / "screenshots" / "2026-09-02" / "screen-15-57-21-158.jpg"
        queue = FileJobQueue(journal / "queue")
        queue.enqueue("vision", {"screenshot": str(existing)}, job_id="existing")
        queue.enqueue("vision", {"screenshot": str(missing)}, job_id="missing")
        return queue

    def test_drop_missing_dead_letters_only_pending_jobs_whose_file_is_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            queue = self._queue_with_jobs(journal)

            exit_code = main(["--journal-root", str(journal), "--drop-missing"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(queue.find("existing")[0], "pending")
            self.assertEqual(queue.find("missing")[0], "failed")

    def test_requeue_failed_skips_jobs_whose_file_is_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            queue = self._queue_with_jobs(journal)
            for job_id in ("existing", "missing"):
                queue.claim()
                queue.fail(job_id, "boom", max_attempts=1)

            main(["--journal-root", str(journal), "--requeue-failed"])

            self.assertEqual(queue.find("existing")[0], "pending")
            self.assertEqual(queue.find("missing")[0], "failed")

    def test_job_without_a_screenshot_path_counts_as_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            queue = FileJobQueue(journal / "queue")
            queue.enqueue("vision", {}, job_id="no-path")

            main(["--journal-root", str(journal), "--drop-missing"])

            self.assertEqual(queue.find("no-path")[0], "failed")


if __name__ == "__main__":
    unittest.main()
