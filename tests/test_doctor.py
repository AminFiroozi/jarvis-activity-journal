import json
import tempfile
import unittest
from pathlib import Path

from src.ops.doctor import doctor_exit_code, run_local_checks


class DoctorTests(unittest.TestCase):
    def test_reports_healthy_local_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "settings.json").write_text(
                json.dumps({"projectPaths": []}), encoding="utf-8"
            )

            checks = run_local_checks(root, minimum_free_bytes=1)

            self.assertTrue(all(check["ok"] for check in checks))
            self.assertEqual(doctor_exit_code(checks), 0)

    def test_missing_settings_is_a_required_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            checks = run_local_checks(Path(directory), minimum_free_bytes=1)

            self.assertTrue(any(not check["ok"] for check in checks))
            self.assertEqual(doctor_exit_code(checks), 1)

    def test_warning_returns_two_when_no_required_check_fails(self):
        checks = [{"name": "optional", "ok": False, "required": False}]

        self.assertEqual(doctor_exit_code(checks), 2)

    def test_warns_when_queue_has_failed_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "settings.json").write_text(json.dumps({"projectPaths": []}), encoding="utf-8")
            (root / "queue" / "failed").mkdir(parents=True)
            (root / "queue" / "failed" / "job1.json").write_text("{}", encoding="utf-8")
            (root / "queue" / "failed" / "job2.json").write_text("{}", encoding="utf-8")

            checks = run_local_checks(root, minimum_free_bytes=1)

            queue_check = next(check for check in checks if check["name"] == "queue-failed")
            self.assertFalse(queue_check["ok"])
            self.assertFalse(queue_check["required"])
            self.assertIn("2", queue_check["detail"])

    def test_queue_failed_check_is_ok_when_empty_or_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "settings.json").write_text(json.dumps({"projectPaths": []}), encoding="utf-8")

            checks = run_local_checks(root, minimum_free_bytes=1)

            queue_check = next(check for check in checks if check["name"] == "queue-failed")
            self.assertTrue(queue_check["ok"])


if __name__ == "__main__":
    unittest.main()
