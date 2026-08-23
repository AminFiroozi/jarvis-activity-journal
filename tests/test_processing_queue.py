import tempfile
import unittest
from pathlib import Path

from src.processing_queue import FileJobQueue


class ProcessingQueueTests(unittest.TestCase):
    def test_enqueue_claim_and_complete_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FileJobQueue(Path(directory))
            created = queue.enqueue("vision", {"screenshot": "screen.jpg"})

            claimed = queue.claim()
            self.assertEqual(claimed["id"], created["id"])
            self.assertEqual(claimed["status"], "processing")

            completed = queue.complete(claimed["id"], {"summary": "coding"})
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["result"]["summary"], "coding")
            self.assertIsNone(queue.claim())

    def test_failed_job_retries_then_enters_dead_letter_state(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FileJobQueue(Path(directory))
            created = queue.enqueue("vision", {})
            first = queue.claim()

            retry = queue.fail(first["id"], "model unavailable", max_attempts=2, retry_delay_seconds=0)
            self.assertEqual(retry["status"], "pending")
            second = queue.claim()
            dead = queue.fail(second["id"], "model unavailable", max_attempts=2, retry_delay_seconds=0)

            self.assertEqual(dead["status"], "failed")
            self.assertEqual(dead["attempts"], 2)
            self.assertEqual(dead["lastError"], "model unavailable")


if __name__ == "__main__":
    unittest.main()
