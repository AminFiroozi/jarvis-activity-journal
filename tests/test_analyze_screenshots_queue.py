import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from src.analysis import analyze_screenshots as module


def _make_journal(directory: Path) -> Path:
    journal = Path(directory)
    screenshot_dir = journal / "screenshots" / "2026-01-01"
    screenshot_dir.mkdir(parents=True)
    image_path = screenshot_dir / "screen-00-00-00-000.jpg"
    Image.new("RGB", (32, 32), color="white").save(image_path, "JPEG")
    config_path = journal / "config" / "settings.json"
    config_path.parent.mkdir(parents=True)
    config = {
        "providers": {"local-vision": {"endpoint": "http://localhost:1234/v1/chat/completions", "model": "m"}},
        "screenshotAnalyzer": {"activeProvider": "local-vision", "maxScreenshotsPerRun": 12, "maxAttempts": 2, "retryDelaySeconds": 0},
        "collectors": {"screenshot": {"dedupeHammingThreshold": 0}},
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return journal


def _run(journal: Path) -> int:
    argv_backup = module.parse_args
    with mock.patch.object(
        module,
        "parse_args",
        return_value=module.argparse.Namespace(
            journal_root=str(journal),
            config=journal / "config" / "settings.json",
            date="2026-01-01",
            context="unknown",
            prompts=module.DEFAULT_PROMPTS,
        ),
    ):
        try:
            return module.main()
        finally:
            module.parse_args = argv_backup


class AnalyzeScreenshotsQueueTests(unittest.TestCase):
    def test_failed_analysis_stays_queued_for_retry_within_max_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", side_effect=ValueError("model unavailable")):
                _run(journal)

            from src.infra.processing_queue import FileJobQueue

            queue = FileJobQueue(journal / "queue")
            pending = list((queue.root / "pending").glob("*.json"))
            self.assertEqual(len(pending), 1)
            job = json.loads(pending[0].read_text(encoding="utf-8"))
            self.assertEqual(job["status"], "pending")
            self.assertEqual(job["attempts"], 1)

    def test_repeated_failure_past_max_attempts_dead_letters_without_losing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", side_effect=ValueError("model unavailable")):
                _run(journal)
                _run(journal)

            from src.infra.processing_queue import FileJobQueue

            queue = FileJobQueue(journal / "queue")
            failed = list((queue.root / "failed").glob("*.json"))
            self.assertEqual(len(failed), 1)
            job = json.loads(failed[0].read_text(encoding="utf-8"))
            self.assertEqual(job["attempts"], 2)
            self.assertIn("model unavailable", job["lastError"])

    def test_successful_analysis_completes_job_and_writes_output(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding"}):
                _run(journal)

            output = journal / "raw" / "visual-2026-01-01.jsonl"
            self.assertTrue(output.exists())
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["analysis"]["summary"], "coding")

            from src.infra.processing_queue import FileJobQueue

            queue = FileJobQueue(journal / "queue")
            self.assertEqual(len(list((queue.root / "completed").glob("*.json"))), 1)

    def test_successful_run_writes_a_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding"}):
                _run(journal)

            heartbeat_path = journal / "health" / "vision-analysis.json"
            self.assertTrue(heartbeat_path.exists())
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "success")
            self.assertEqual(heartbeat["itemsProcessed"], 1)

    def test_failed_run_writes_a_failed_heartbeat_when_nothing_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", side_effect=ValueError("model unavailable")):
                _run(journal)

            heartbeat_path = journal / "health" / "vision-analysis.json"
            self.assertTrue(heartbeat_path.exists())
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "failed")
            self.assertEqual(heartbeat["itemsProcessed"], 0)

    def test_successful_analysis_writes_a_markdown_file_for_the_screenshot(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            analysis = {"summary": "coding", "screen_details": ["editor shows main.py"]}
            with mock.patch.object(module, "call_vision", return_value=analysis):
                _run(journal)

            target = journal / "screens" / "2026-01-01" / "00" / "00-00-00-000.md"
            self.assertTrue(target.exists())
            text = target.read_text(encoding="utf-8")
            self.assertIn("coding", text)
            self.assertIn("- editor shows main.py", text)

    def test_near_duplicate_screenshot_gets_an_unchanged_file_without_a_second_call(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            screenshot_dir = journal / "screenshots" / "2026-01-01"
            first = screenshot_dir / "screen-00-00-00-000.jpg"
            second = screenshot_dir / "screen-00-01-00-000.jpg"
            Image.new("RGB", (32, 32), color="white").save(second, "JPEG")
            os.utime(first, (1000, 1000))
            os.utime(second, (2000, 2000))
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding"}) as mocked:
                _run(journal)

            self.assertEqual(mocked.call_count, 1)
            duplicate = journal / "screens" / "2026-01-01" / "00" / "00-01-00-000.md"
            self.assertTrue(duplicate.exists())
            self.assertIn("Unchanged since 00:00:00.", duplicate.read_text(encoding="utf-8"))

    def test_screenshot_that_already_has_a_file_is_not_queued_again(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            existing = journal / "screens" / "2026-01-01" / "00" / "00-00-00-000.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("# Screen\n", encoding="utf-8")
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding"}) as mocked:
                _run(journal)

            mocked.assert_not_called()

    def test_result_is_filed_under_the_screenshots_own_date(self):
        from src.infra.processing_queue import FileJobQueue

        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            (journal / "screenshots" / "2026-01-01" / "screen-00-00-00-000.jpg").unlink()
            older_dir = journal / "screenshots" / "2025-12-31"
            older_dir.mkdir(parents=True)
            image = older_dir / "screen-23-59-00-000.jpg"
            Image.new("RGB", (32, 32), color="white").save(image, "JPEG")
            FileJobQueue(journal / "queue").enqueue(
                "vision",
                {"screenshot": str(image), "date": "2025-12-31", "context": "unknown"},
                job_id=module.job_id_for(image),
            )
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding"}):
                _run(journal)

            older = journal / "raw" / "visual-2025-12-31.jsonl"
            self.assertTrue(older.exists())
            self.assertEqual(json.loads(older.read_text(encoding="utf-8").splitlines()[0])["screenshot"], str(image))
            self.assertFalse((journal / "raw" / "visual-2026-01-01.jsonl").exists())

    def test_analysed_screenshot_missing_its_file_is_repaired_without_pending_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            image = journal / "screenshots" / "2026-01-01" / "screen-00-00-00-000.jpg"
            record = {"timestamp": "2026-01-01T00:00:00+00:00", "source": "screenshot-vision", "screenshot": str(image), "analysis": {"summary": "coding"}}
            (journal / "raw").mkdir()
            (journal / "raw" / "visual-2026-01-01.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            with mock.patch.object(module, "call_vision", return_value={"summary": "other"}) as mocked:
                _run(journal)

            mocked.assert_not_called()
            target = journal / "screens" / "2026-01-01" / "00" / "00-00-00-000.md"
            self.assertTrue(target.exists())
            self.assertIn("coding", target.read_text(encoding="utf-8"))

    def test_duplicate_of_screenshot_analysed_in_earlier_run_is_filed_without_pending_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            screenshot_dir = journal / "screenshots" / "2026-01-01"
            kept = screenshot_dir / "screen-00-00-00-000.jpg"
            duplicate = screenshot_dir / "screen-00-01-00-000.jpg"
            Image.new("RGB", (32, 32), color="white").save(duplicate, "JPEG")
            record = {"timestamp": "2026-01-01T00:00:00+00:00", "source": "screenshot-vision", "screenshot": str(kept), "analysis": {"summary": "coding"}}
            (journal / "raw").mkdir()
            (journal / "raw" / "visual-2026-01-01.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            (journal / "raw" / "screen-dups-2026-01-01.json").write_text(json.dumps({str(duplicate): str(kept)}), encoding="utf-8")
            with mock.patch.object(module, "call_vision", return_value={"summary": "other"}) as mocked:
                _run(journal)

            mocked.assert_not_called()
            target = journal / "screens" / "2026-01-01" / "00" / "00-01-00-000.md"
            self.assertTrue(target.exists())
            self.assertIn("Unchanged since 00:00:00.", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
