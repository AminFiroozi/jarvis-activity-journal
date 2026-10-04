import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.orchestration.daily_summary import keep_existing_narrative, main


class DailySummaryVaultRootGatingTests(unittest.TestCase):
    def _invoke_main(self, journal_root: Path, config_path: Path, date: str):
        mock_result = MagicMock()
        mock_result.returncode = 0
        old_argv = sys.argv
        sys.argv = [
            "daily_summary",
            "--journal-root", str(journal_root),
            "--config", str(config_path),
            "--date", date,
        ]
        try:
            with patch(
                "src.orchestration.daily_summary.subprocess.run",
                return_value=mock_result,
            ) as mock_run:
                exit_code = main()
        finally:
            sys.argv = old_argv
        return exit_code, mock_run

    def _sync_vault_calls(self, mock_run):
        return [
            call for call in mock_run.call_args_list
            if "src.orchestration.sync_vault" in call.args[0]
        ]

    def _sync_entities_calls(self, mock_run):
        return [
            call for call in mock_run.call_args_list
            if "src.orchestration.sync_entities" in call.args[0]
        ]

    def test_sync_vault_invoked_when_vault_root_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(
                json.dumps({"vaultRoot": str(root / "vault")}), encoding="utf-8"
            )

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-28")

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(self._sync_vault_calls(mock_run)), 1)

    def test_sync_vault_not_invoked_when_vault_root_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-28")

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(self._sync_vault_calls(mock_run)), 0)

    def test_sync_entities_invoked_when_vault_root_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(
                json.dumps({"vaultRoot": str(root / "vault")}), encoding="utf-8"
            )

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-28")

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(self._sync_entities_calls(mock_run)), 1)

    def test_sync_entities_not_invoked_when_vault_root_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-28")

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(self._sync_entities_calls(mock_run)), 0)

    def test_main_does_not_raise_on_malformed_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text("{not valid json", encoding="utf-8")

            exit_code, mock_run = self._invoke_main(journal_root, config_path, "2026-08-28")

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(self._sync_vault_calls(mock_run)), 0)


class DailySummaryChainTests(unittest.TestCase):
    def test_periods_run_hourly_before_daily_before_weekly_and_never_the_old_daily_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            journal_root.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")
            mock_result = MagicMock()
            mock_result.returncode = 0
            old_argv = sys.argv
            sys.argv = ["daily_summary", "--journal-root", str(journal_root), "--config", str(config_path), "--date", "2026-08-30"]
            try:
                with patch("src.orchestration.daily_summary.subprocess.run", return_value=mock_result) as mock_run:
                    exit_code = main()
            finally:
                sys.argv = old_argv

            self.assertEqual(exit_code, 0)
            commands = [call.args[0] for call in mock_run.call_args_list]
            periods = [command[command.index("--period") + 1] for command in commands if "src.analysis.synthesize_period" in command]
            self.assertEqual(periods, ["hourly", "daily", "weekly"])
            self.assertFalse(any("src.analysis.synthesize_journal" in command for command in commands))


class KeepExistingNarrativeTests(unittest.TestCase):
    def test_appends_the_existing_narrative_with_its_stamp_once(self):
        scaffold = "# Journal\n\n## Applications\n\n- Code\n"
        existing = "# Old\n\n## Applications\n\n- Old\n\n## LLM narrative\n\nWorked on Kibana.\n\n<!-- input: abc123 -->\n"

        result = keep_existing_narrative(scaffold, existing)

        self.assertIn("- Code", result)
        self.assertNotIn("- Old", result)
        self.assertEqual(result.count("## LLM narrative"), 1)
        self.assertEqual(result.count("Worked on Kibana."), 1)
        self.assertEqual(result.count("<!-- input: abc123 -->"), 1)

    def test_existing_without_a_narrative_returns_the_scaffold_unchanged(self):
        scaffold = "# Journal\n\n- Code\n"
        self.assertEqual(keep_existing_narrative(scaffold, "# Old\n\n- Old\n"), scaffold)
        self.assertEqual(keep_existing_narrative(scaffold, ""), scaffold)

    def test_main_keeps_the_narrative_and_stamp_when_rewriting_the_scaffold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            (journal_root / "daily").mkdir(parents=True)
            date = "2026-08-28"
            (journal_root / "daily" / f"{date}.md").write_text(
                "# Old\n\n## LLM narrative\n\nWorked on Kibana.\n\n<!-- input: abc123 -->\n", encoding="utf-8"
            )
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")
            mock_result = MagicMock()
            mock_result.returncode = 1
            old_argv = sys.argv
            sys.argv = ["daily_summary", "--journal-root", str(journal_root), "--config", str(config_path), "--date", date]
            try:
                with patch("src.orchestration.daily_summary.subprocess.run", return_value=mock_result):
                    main()
            finally:
                sys.argv = old_argv

            text = (journal_root / "daily" / f"{date}.md").read_text(encoding="utf-8")
            self.assertIn(f"# Automatic Activity Journal — {date}", text)
            self.assertIn("Worked on Kibana.", text)
            self.assertIn("<!-- input: abc123 -->", text)


if __name__ == "__main__":
    unittest.main()
