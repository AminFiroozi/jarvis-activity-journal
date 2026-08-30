import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.orchestration.run_hourly import main


class RunHourlyWiringTests(unittest.TestCase):
    def _invoke_main(self, journal_root: Path, config_path: Path, date: str):
        mock_result = MagicMock()
        mock_result.returncode = 0
        old_argv = sys.argv
        sys.argv = [
            "run_hourly",
            "--journal-root", str(journal_root),
            "--config", str(config_path),
            "--date", date,
        ]
        try:
            with patch(
                "src.orchestration.run_hourly.subprocess.run",
                return_value=mock_result,
            ) as mock_run:
                exit_code = main()
        finally:
            sys.argv = old_argv
        return exit_code, mock_run

    def _calls_containing(self, mock_run, needle: str):
        return [call for call in mock_run.call_args_list if needle in call.args[0]]

    def test_build_journals_is_no_longer_invoked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text("{}", encoding="utf-8")

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-30")

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(self._calls_containing(mock_run, "src.analysis.build_journals")), 0)

    def test_synthesize_period_is_invoked_for_both_hourly_and_weekly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text("{}", encoding="utf-8")

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-30")

            self.assertEqual(exit_code, 0)
            period_calls = self._calls_containing(mock_run, "src.analysis.synthesize_period")
            self.assertEqual(len(period_calls), 2)
            periods = {call.args[0][call.args[0].index("--period") + 1] for call in period_calls}
            self.assertEqual(periods, {"hourly", "weekly"})


if __name__ == "__main__":
    unittest.main()
