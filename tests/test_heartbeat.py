import json
import tempfile
import unittest
from pathlib import Path

from src.heartbeat import write_heartbeat


class HeartbeatTests(unittest.TestCase):
    def test_writes_and_preserves_started_at(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_path = write_heartbeat(root, "collector", "started")
            first = json.loads(first_path.read_text(encoding="utf-8"))

            second_path = write_heartbeat(root, "collector", "success", items_processed=3)
            second = json.loads(second_path.read_text(encoding="utf-8"))

            self.assertEqual(second["startedAt"], first["startedAt"])
            self.assertEqual(second["itemsProcessed"], 3)
            self.assertIsNotNone(second["lastSuccessAt"])

    def test_failed_status_records_error_and_keeps_last_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_heartbeat(root, "collector", "success", items_processed=1)
            path = write_heartbeat(root, "collector", "failed", error_message="boom")
            state = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["lastError"], "boom")
            self.assertIsNotNone(state["lastSuccessAt"])

    def test_rejects_invalid_status(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                write_heartbeat(Path(directory), "collector", "bogus")


if __name__ == "__main__":
    unittest.main()
