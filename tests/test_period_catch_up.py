import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.orchestration import daily_summary, run_hourly


def _mock_run():
    result = MagicMock()
    result.returncode = 0
    return result


class CatchUpTests(unittest.TestCase):
    """A finished day's last hour keeps gaining screenshots after midnight, so its reports
    must be revisited. Unchanged reports cost nothing: the input stamp skips them."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        self.journal_root = root / "journal"
        self.journal_root.mkdir()
        self.config_path = root / "settings.json"
        self.config_path.write_text("{}", encoding="utf-8")
        self.date = "2026-08-30"
        self.yesterday = (dt.date.fromisoformat(self.date) - dt.timedelta(days=1)).isoformat()

    def tearDown(self):
        self._temp.cleanup()

    def _run_hourly(self, extra_argv=()):
        old_argv = sys.argv
        sys.argv = [
            "run_hourly",
            "--journal-root", str(self.journal_root),
            "--config", str(self.config_path),
            "--date", self.date,
            *extra_argv,
        ]
        try:
            with patch("src.orchestration.run_hourly.subprocess.run", return_value=_mock_run()) as mock_run:
                exit_code = run_hourly.main()
        finally:
            sys.argv = old_argv
        return exit_code, mock_run

    def _synthesize_dates(self, mock_run):
        dates = []
        for call in mock_run.call_args_list:
            argv = call.args[0]
            if "src.analysis.synthesize_period" in argv:
                dates.append(argv[argv.index("--date") + 1])
        return dates

    def test_run_hourly_covers_yesterday_as_well_as_today(self):
        exit_code, mock_run = self._run_hourly()

        self.assertEqual(exit_code, 0)
        dates = self._synthesize_dates(mock_run)
        self.assertIn(self.date, dates)
        self.assertIn(self.yesterday, dates)

    def test_yesterday_runs_the_full_chain_not_just_hourly(self):
        _, mock_run = self._run_hourly()

        for period in ("hourly", "daily", "weekly"):
            argv_sets = [
                call.args[0]
                for call in mock_run.call_args_list
                if "src.analysis.synthesize_period" in call.args[0]
                and call.args[0][call.args[0].index("--period") + 1] == period
            ]
            self.assertTrue(
                any(argv[argv.index("--date") + 1] == self.yesterday for argv in argv_sets),
                f"{period} was not run for yesterday",
            )

    def test_catch_up_can_be_turned_off(self):
        _, mock_run = self._run_hourly(extra_argv=("--catch-up-days", "0"))

        dates = self._synthesize_dates(mock_run)
        self.assertNotIn(self.yesterday, dates)

    def test_daily_summary_also_catches_up_yesterday(self):
        old_argv = sys.argv
        sys.argv = [
            "daily_summary",
            "--journal-root", str(self.journal_root),
            "--config", str(self.config_path),
            "--date", self.date,
        ]
        try:
            with patch.object(daily_summary.subprocess, "run", return_value=_mock_run()):
                exit_code = daily_summary.main()
        finally:
            sys.argv = old_argv

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()