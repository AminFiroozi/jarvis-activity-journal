import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analysis.report_render import NARRATIVE_MARKER, read_input_stamp
from src.analysis.synthesize_period import (
    STAGE_KEYS,
    activity_lines,
    build_report,
    call_report_model,
    gather_day,
    gather_hour,
    gather_week,
    hours_with_input,
    main,
    week_dates,
)

DATE = "2026-09-26"
CANNED = json.dumps({
    "summary": "Worked on dashboards.",
    "on_screen": ["Kibana dashboard kassa-log"],
    "timeline": [{"time": "10:21", "activity": "Opened Kibana"}],
    "patterns": ["Log review"],
    "next_actions": ["Check errors"],
})
PROVIDER = {"name": "test"}


def _screen(journal: Path, date: str, hour: int, clock: str, body: str = "Viewing Kibana.") -> Path:
    path = journal / "screens" / date / f"{hour:02d}" / f"{clock}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Screen — {date} {clock[:8].replace('-', ':')}\n\n{body}\n", encoding="utf-8")
    return path


def _activity(journal: Path, date: str, events: list[dict]) -> None:
    raw = journal / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"activity-{date}.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def _window(stamp: str, process: str | None, title: str | None = None, executable: str | None = None) -> dict:
    return {"source": "foreground-window", "localTimestamp": f"{stamp}+03:30", "process": process, "executable": executable, "windowTitle": title}


class WeekDatesTests(unittest.TestCase):
    def test_returns_monday_through_the_given_date(self):
        year, week, dates = week_dates("2026-08-27")
        self.assertEqual(dates, ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"])
        self.assertEqual((year, week), (2026, 35))


class ActivityLinesTests(unittest.TestCase):
    def test_collapses_consecutive_identical_windows_and_ignores_other_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _activity(journal, DATE, [
                _window("2026-09-26T10:00:10", "remmina", "311", "/usr/bin/remmina"),
                _window("2026-09-26T10:01:10", "remmina", "311", "/usr/bin/remmina"),
                _window("2026-09-26T10:02:10", "chrome", "Kibana", "/opt/google/chrome/chrome"),
                _window("2026-09-26T11:00:10", "code", "main.py"),
            ])

            lines = activity_lines(journal, DATE, 10)

            self.assertEqual(lines, ["10:00–10:01 remmina — 311", "10:02 chrome — Kibana"])

    def test_events_without_a_process_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _activity(journal, DATE, [_window("2026-09-26T18:13:00", None)])

            self.assertEqual(activity_lines(journal, DATE, 18), [])


class HoursWithInputTests(unittest.TestCase):
    def test_union_of_screen_hours_and_activity_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 9, "09-05-16-374")
            _activity(journal, DATE, [_window("2026-09-26T14:00:10", "code", "x"), _window("2026-09-26T15:00:10", None)])

            self.assertEqual(hours_with_input(journal, DATE), [9, 14])


class GatherTests(unittest.TestCase):
    def test_hour_with_nothing_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(gather_hour(Path(directory), DATE, 10))

    def test_hour_with_only_no_active_window_events_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _activity(journal, DATE, [_window("2026-09-26T18:13:00", None)])

            self.assertIsNone(gather_hour(journal, DATE, 18))

    def test_hour_includes_screens_and_activity_and_counts_repeats_without_including_them(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521", "Viewing Kibana.")
            _screen(journal, DATE, 10, "10-22-15-521", "Viewing Kibana.\n\nUnchanged since 10:21:15.")
            _activity(journal, DATE, [_window("2026-09-26T10:21:00", "chrome", "Kibana")])

            text = gather_hour(journal, DATE, 10)

            self.assertIn("10:21:15", text)
            self.assertNotIn("10:22:15", text)
            self.assertIn("1 further screenshot(s) were unchanged repeats", text)
            self.assertIn("chrome — Kibana", text)

    def test_hour_source_text_ignores_the_stamp_comment_in_screen_files(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            path = _screen(journal, DATE, 10, "10-21-15-521")
            path.write_text(path.read_text(encoding="utf-8") + "\n<!-- input: abc123 -->\n", encoding="utf-8")

            self.assertNotIn("<!--", gather_hour(journal, DATE, 10))

    def test_day_reads_only_hourly_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "hourly" / DATE).mkdir(parents=True)
            (journal / "hourly" / DATE / "10.md").write_text("# Hourly journal — 2026-09-26 10:00\n\nKibana hour.\n", encoding="utf-8")
            (journal / "hourly" / DATE / "11.md").write_text("# Hourly journal — 2026-09-26 11:00\n\nCoding hour.\n", encoding="utf-8")
            _screen(journal, DATE, 12, "12-00-00-000", "should not appear")

            text = gather_day(journal, DATE)

            self.assertLess(text.index("Kibana hour."), text.index("Coding hour."))
            self.assertNotIn("should not appear", text)
            self.assertIsNone(gather_day(journal, "2026-01-01"))

    def test_week_reads_daily_narratives_and_skips_days_without_one(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "daily").mkdir()
            (journal / "daily" / "2026-09-21.md").write_text(f"# D\n\n## Applications\n\nscaffold-only\n\n{NARRATIVE_MARKER}\n\nMonday summary.\n", encoding="utf-8")
            (journal / "daily" / "2026-09-22.md").write_text("# D\n\n## Applications\n\nno narrative yet\n", encoding="utf-8")

            text = gather_week(journal, "2026-09-23")

            self.assertIn("Monday summary.", text)
            self.assertIn("2026-09-21", text)
            self.assertNotIn("scaffold-only", text)
            self.assertNotIn("no narrative yet", text)

    def test_week_with_no_narratives_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(gather_week(Path(directory), "2026-09-23"))


class CallReportModelTests(unittest.TestCase):
    def test_retries_once_on_invalid_json_then_succeeds(self):
        with mock.patch("src.analysis.synthesize_period.call_chat_completions", side_effect=['{"summary": "x",', CANNED]) as mocked:
            result = call_report_model(PROVIDER, "hourly", "sources")

        self.assertEqual(result["summary"], "Worked on dashboards.")
        self.assertEqual(mocked.call_count, 2)
        retry_messages = mocked.call_args.args[1]
        self.assertEqual(retry_messages[-1]["role"], "user")
        self.assertIn("not valid JSON", retry_messages[-1]["content"])

    def test_two_invalid_responses_raise_value_error(self):
        with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value="nope"):
            with self.assertRaises(ValueError):
                call_report_model(PROVIDER, "hourly", "sources")

    def test_system_prompt_is_the_level_prompt(self):
        from src.analysis.report_levels import build_prompt

        with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
            call_report_model(PROVIDER, "weekly", "sources")

        self.assertEqual(mocked.call_args.args[1][0]["content"], build_prompt("weekly"))


class BuildReportTests(unittest.TestCase):
    def test_hourly_report_is_written_with_shared_format_and_stamp(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                result = build_report(PROVIDER, journal, "hourly", DATE, hour=10)

            path = journal / "hourly" / DATE / "10.md"
            self.assertEqual(result, {"status": "complete", "path": str(path)})
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Hourly journal — 2026-09-26 10:00\n\nWorked on dashboards.\n"))
            self.assertIn("### On screen", text)
            self.assertIsNotNone(read_input_stamp(text))
            self.assertNotIn("confidence", text.lower())
            self.assertNotIn("Next actions", text)

    def test_unchanged_input_skips_the_model_and_changed_input_rebuilds(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
                build_report(PROVIDER, journal, "hourly", DATE, hour=10)
                second = build_report(PROVIDER, journal, "hourly", DATE, hour=10)
                self.assertEqual(second["status"], "unchanged")
                self.assertEqual(mocked.call_count, 1)

                _screen(journal, DATE, 10, "10-30-00-000", "A new screen.")
                third = build_report(PROVIDER, journal, "hourly", DATE, hour=10)
                self.assertEqual(third["status"], "complete")
                self.assertEqual(mocked.call_count, 2)

    def test_changing_the_report_format_version_rebuilds_an_unchanged_report(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
                build_report(PROVIDER, journal, "hourly", DATE, hour=10)
                with mock.patch("src.analysis.synthesize_period.REPORT_FORMAT_VERSION", "next"):
                    result = build_report(PROVIDER, journal, "hourly", DATE, hour=10)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(mocked.call_count, 2)

    def test_no_input_writes_nothing_and_never_calls_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions") as mocked:
                result = build_report(PROVIDER, journal, "hourly", DATE, hour=3)

            mocked.assert_not_called()
            self.assertEqual(result, {"status": "no-input"})
            self.assertFalse((journal / "hourly").exists())

    def test_failed_model_call_leaves_no_file_so_the_next_run_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            _screen(journal, DATE, 10, "10-21-15-521")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value="nope"):
                with self.assertRaises(ValueError):
                    build_report(PROVIDER, journal, "hourly", DATE, hour=10)

            self.assertFalse((journal / "hourly" / DATE / "10.md").exists())

    def test_daily_report_keeps_the_scaffold_and_adds_the_narrative_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "hourly" / DATE).mkdir(parents=True)
            (journal / "hourly" / DATE / "10.md").write_text("# Hourly journal — 2026-09-26 10:00\n\nKibana hour.\n", encoding="utf-8")
            (journal / "daily").mkdir()
            (journal / "daily" / f"{DATE}.md").write_text("# Automatic Activity Journal — 2026-09-26\n\n## Applications\n\n- Code\n", encoding="utf-8")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                result = build_report(PROVIDER, journal, "daily", DATE)

            text = (journal / "daily" / f"{DATE}.md").read_text(encoding="utf-8")
            self.assertEqual(result["status"], "complete")
            self.assertIn("## Applications", text)
            self.assertIn(NARRATIVE_MARKER, text)
            self.assertIn("### On screen", text)
            self.assertIsNotNone(read_input_stamp(text))

    def test_daily_rewritten_by_the_scaffold_is_rebuilt_even_if_input_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "hourly" / DATE).mkdir(parents=True)
            (journal / "hourly" / DATE / "10.md").write_text("# Hourly\n\nKibana hour.\n", encoding="utf-8")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
                build_report(PROVIDER, journal, "daily", DATE)
                (journal / "daily" / f"{DATE}.md").write_text("# Automatic Activity Journal — 2026-09-26\n", encoding="utf-8")
                result = build_report(PROVIDER, journal, "daily", DATE)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(mocked.call_count, 2)

    def test_weekly_report_path_uses_iso_week(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "daily").mkdir()
            (journal / "daily" / "2026-09-21.md").write_text(f"# D\n\n{NARRATIVE_MARKER}\n\nMonday summary.\n", encoding="utf-8")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                result = build_report(PROVIDER, journal, "weekly", "2026-09-23")

            self.assertEqual(result["path"], str(journal / "weekly" / "2026-W39.md"))
            self.assertTrue(result["path"].endswith("2026-W39.md"))
            self.assertTrue(Path(result["path"]).read_text(encoding="utf-8").startswith("# Weekly journal — 2026-W39\n"))


def _config(journal: Path, stage: str = "hourlySynthesis", **stage_overrides) -> Path:
    config_path = journal.parent / "settings.json"
    config_path.write_text(json.dumps({
        stage: {"enabled": True, "activeProvider": "test-provider", **stage_overrides},
        "providers": {"test-provider": {"endpoint": "http://x", "model": "m"}},
    }), encoding="utf-8")
    return config_path


def _run_main(journal: Path, config_path: Path, period: str, date: str = DATE) -> int:
    old_argv = sys.argv
    sys.argv = ["synthesize_period", "--journal-root", str(journal), "--config", str(config_path), "--period", period, "--date", date]
    try:
        return main()
    finally:
        sys.argv = old_argv


class MainTests(unittest.TestCase):
    def test_stage_keys(self):
        self.assertEqual(STAGE_KEYS, {"hourly": "hourlySynthesis", "daily": "journalSynthesis", "weekly": "weeklySynthesis"})

    def test_hourly_builds_every_hour_with_input_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            _screen(journal, DATE, 9, "09-05-16-374")
            _screen(journal, DATE, 14, "14-10-00-000")
            config_path = _config(journal)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED) as mocked:
                first = _run_main(journal, config_path, "hourly")
                second = _run_main(journal, config_path, "hourly")

            self.assertEqual((first, second), (0, 0))
            self.assertEqual(mocked.call_count, 2)
            self.assertTrue((journal / "hourly" / DATE / "09.md").exists())
            self.assertTrue((journal / "hourly" / DATE / "14.md").exists())

    def test_disabled_stage_does_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            _screen(journal, DATE, 9, "09-05-16-374")
            config_path = _config(journal, enabled=False)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions") as mocked:
                exit_code = _run_main(journal, config_path, "hourly")

            self.assertEqual(exit_code, 0)
            mocked.assert_not_called()

    def test_missing_provider_returns_one_and_writes_a_failed_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({"hourlySynthesis": {"enabled": True}}), encoding="utf-8")

            exit_code = _run_main(journal, config_path, "hourly")

            self.assertEqual(exit_code, 1)
            heartbeat = json.loads((journal / "health" / "hourly-synthesis.json").read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "failed")

    def test_model_failure_returns_one_and_a_later_run_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            _screen(journal, DATE, 9, "09-05-16-374")
            config_path = _config(journal)
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value="nope"):
                failed = _run_main(journal, config_path, "hourly")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                recovered = _run_main(journal, config_path, "hourly")

            self.assertEqual((failed, recovered), (1, 0))
            self.assertTrue((journal / "hourly" / DATE / "09.md").exists())

    def test_daily_period_uses_the_journal_synthesis_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            (journal / "hourly" / DATE).mkdir(parents=True)
            (journal / "hourly" / DATE / "10.md").write_text("# Hourly\n\nKibana hour.\n", encoding="utf-8")
            config_path = _config(journal, stage="journalSynthesis")
            with mock.patch("src.analysis.synthesize_period.call_chat_completions", return_value=CANNED):
                exit_code = _run_main(journal, config_path, "daily")

            self.assertEqual(exit_code, 0)
            self.assertIn(NARRATIVE_MARKER, (journal / "daily" / f"{DATE}.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
