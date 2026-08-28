import os
import tempfile
import time
import unittest
from pathlib import Path

from src.infra.retention import run_retention


class RetentionTests(unittest.TestCase):
    def test_removes_only_files_older_than_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            old_file = raw / "old.jsonl"
            new_file = raw / "new.jsonl"
            old_file.write_text("old", encoding="utf-8")
            new_file.write_text("new", encoding="utf-8")
            old_time = time.time() - (200 * 86400)
            os.utime(old_file, (old_time, old_time))

            result = run_retention(root, retention_days=90)

            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
            self.assertEqual(result["removedFiles"], 1)

    def test_missing_subdirectories_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_retention(Path(directory), retention_days=30)
            self.assertEqual(result["removedFiles"], 0)

    def test_removes_old_completed_and_failed_queue_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for state in ("completed", "failed", "pending", "processing"):
                (root / "queue" / state).mkdir(parents=True)
            old_completed = root / "queue" / "completed" / "old.json"
            old_failed = root / "queue" / "failed" / "old.json"
            new_pending = root / "queue" / "pending" / "new.json"
            for path in (old_completed, old_failed, new_pending):
                path.write_text("{}", encoding="utf-8")
            old_time = time.time() - (200 * 86400)
            os.utime(old_completed, (old_time, old_time))
            os.utime(old_failed, (old_time, old_time))

            result = run_retention(root, retention_days=90)

            self.assertFalse(old_completed.exists())
            self.assertFalse(old_failed.exists())
            self.assertTrue(new_pending.exists())
            self.assertEqual(result["removedFiles"], 2)


if __name__ == "__main__":
    unittest.main()
