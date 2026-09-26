import tempfile
import unittest
from pathlib import Path

from src.infra.processing_queue import FileJobQueue


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

    def test_enqueue_with_job_id_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FileJobQueue(Path(directory))
            first = queue.enqueue("vision", {"screenshot": "screen.jpg"}, job_id="screen-jpg")
            second = queue.enqueue("vision", {"screenshot": "screen.jpg"}, job_id="screen-jpg")

            self.assertEqual(first["id"], second["id"])
            self.assertEqual(len(list((Path(directory) / "pending").glob("*.json"))), 1)

    def test_find_locates_job_across_states(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FileJobQueue(Path(directory))
            created = queue.enqueue("vision", {}, job_id="job-1")

            state, job = queue.find("job-1")
            self.assertEqual(state, "pending")
            self.assertEqual(job["id"], created["id"])
            self.assertIsNone(queue.find("missing"))

    def test_claim_filters_by_kind(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FileJobQueue(Path(directory))
            queue.enqueue("synthesis", {}, job_id="s-1")
            vision_job = queue.enqueue("vision", {}, job_id="v-1")

            claimed = queue.claim(kind="vision")
            self.assertEqual(claimed["id"], vision_job["id"])

    def test_claim_excludes_given_ids_without_mutating_them(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FileJobQueue(Path(directory))
            job = queue.enqueue("vision", {}, job_id="v-1")

            claimed = queue.claim(kind="vision", exclude_ids={job["id"]})

            self.assertIsNone(claimed)
            self.assertEqual(len(list((Path(directory) / "pending").glob("*.json"))), 1)
            _, unchanged = queue.find(job["id"])
            self.assertEqual(unchanged["attempts"], 0)
            self.assertEqual(unchanged["status"], "pending")

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

    def test_requeue_failed_moves_matching_jobs_back_to_pending_with_fresh_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FileJobQueue(Path(directory))
            queue.enqueue("vision", {"screenshot": "a.jpg"}, job_id="a")
            queue.enqueue("hourly", {"date": "2026-09-26"}, job_id="b")
            for job_id in ("a", "b"):
                queue.claim()
                queue.fail(job_id, "boom", max_attempts=1)

            moved = queue.requeue_failed(kind="vision")

            self.assertEqual(moved, 1)
            state, job = queue.find("a")
            self.assertEqual((state, job["attempts"], job["status"]), ("pending", 0, "pending"))
            self.assertNotIn("failedAt", job)
            self.assertEqual(queue.find("b")[0], "failed")
            self.assertIsNotNone(queue.claim(kind="vision"))


if __name__ == "__main__":
    unittest.main()
