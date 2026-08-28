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


if __name__ == "__main__":
    unittest.main()
