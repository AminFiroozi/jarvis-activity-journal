import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.orchestration.daily_summary import main


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


if __name__ == "__main__":
    unittest.main()
