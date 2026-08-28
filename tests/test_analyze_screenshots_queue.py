import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from src import analyze_screenshots as module


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

            from src.processing_queue import FileJobQueue

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

            from src.processing_queue import FileJobQueue

            queue = FileJobQueue(journal / "queue")
            failed = list((queue.root / "failed").glob("*.json"))
            self.assertEqual(len(failed), 1)
            job = json.loads(failed[0].read_text(encoding="utf-8"))
            self.assertEqual(job["attempts"], 2)
            self.assertIn("model unavailable", job["lastError"])

    def test_successful_analysis_completes_job_and_writes_output(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = _make_journal(Path(directory))
            with mock.patch.object(module, "call_vision", return_value={"summary": "coding", "confidence": 0.9}):
                _run(journal)

            output = journal / "raw" / "visual-2026-01-01.jsonl"
            self.assertTrue(output.exists())
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["analysis"]["summary"], "coding")

            from src.processing_queue import FileJobQueue

            queue = FileJobQueue(journal / "queue")
            self.assertEqual(len(list((queue.root / "completed").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
