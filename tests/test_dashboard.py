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


if __name__ == "__main__":
    unittest.main()
