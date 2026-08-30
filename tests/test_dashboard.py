import json
import tempfile
import unittest
from pathlib import Path

from src.ops.dashboard import build_status


class DashboardTests(unittest.TestCase):
    def test_status_reports_health_and_latest_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "health").mkdir()
            (root / "daily").mkdir()
            (root / "health" / "collector.json").write_text(
                json.dumps({"service": "collector", "status": "success", "updatedAt": "now"}),
                encoding="utf-8",
            )
            (root / "daily" / "2026-08-23.md").write_text("# Today", encoding="utf-8")

            status = build_status(root)

            self.assertEqual(status["health"][0]["service"], "collector")
            self.assertEqual(status["latestJournal"], "2026-08-23.md")

    def test_status_reports_queue_period_job_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "queue-period" / "pending").mkdir(parents=True)
            (root / "queue-period" / "failed").mkdir(parents=True)
            (root / "queue-period" / "pending" / "job1.json").write_text("{}", encoding="utf-8")
            (root / "queue-period" / "failed" / "job2.json").write_text("{}", encoding="utf-8")
            (root / "queue-period" / "failed" / "job3.json").write_text("{}", encoding="utf-8")

            status = build_status(root)

            self.assertEqual(
                status["queuePeriod"],
                {"pending": 1, "processing": 0, "completed": 0, "failed": 2},
            )


if __name__ == "__main__":
    unittest.main()
