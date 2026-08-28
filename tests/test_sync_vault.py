import sys
import tempfile
import unittest
from pathlib import Path

from src.orchestration.sync_vault import main, render_vault_note, sync_day


class SyncVaultTests(unittest.TestCase):
    def test_sync_day_returns_none_when_source_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            vault_root = root / "vault"
            journal_root.mkdir()
            vault_root.mkdir()

            result = sync_day(journal_root, vault_root, "2026-08-28")

            self.assertIsNone(result)

    def test_sync_day_writes_note_with_frontmatter_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            vault_root = root / "vault"
            (journal_root / "daily").mkdir(parents=True)
            (journal_root / "daily" / "2026-08-28.md").write_text(
                "# Automatic Activity Journal — 2026-08-28\n\nChatted with Dariush about the project.\n",
                encoding="utf-8",
            )
            friends = vault_root / "People" / "Friends"
            friends.mkdir(parents=True)
            (friends / "DariushSeif.md").write_text("", encoding="utf-8")

            result = sync_day(journal_root, vault_root, "2026-08-28")

            self.assertEqual(result, vault_root / "Journal" / "Daily" / "2026-08-28.md")
            written = result.read_text(encoding="utf-8")
            self.assertIn("date: 2026-08-28", written)
            self.assertIn("tags: [activity-journal, generated]", written)
            self.assertIn("[[DariushSeif|Dariush]]", written)

    def test_sync_day_overwrites_on_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            vault_root = root / "vault"
            (journal_root / "daily").mkdir(parents=True)
            source = journal_root / "daily" / "2026-08-28.md"
            source.write_text("First version.\n", encoding="utf-8")

            first = sync_day(journal_root, vault_root, "2026-08-28")
            source.write_text("Second version.\n", encoding="utf-8")
            second = sync_day(journal_root, vault_root, "2026-08-28")

            self.assertEqual(first, second)
            second_text = second.read_text(encoding="utf-8")
            self.assertIn("Second version.", second_text)
            self.assertNotIn("First version.", second_text)

    def test_render_vault_note_shape(self):
        note = render_vault_note("2026-08-28", "Some content.")

        self.assertTrue(note.startswith("---\ndate: 2026-08-28\ntags: [activity-journal, generated]\n---\n\n"))
        self.assertIn("Some content.", note)

    def test_main_exits_zero_and_warns_on_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_root = root / "journal"
            (journal_root / "daily").mkdir(parents=True)
            (journal_root / "daily" / "2026-08-28.md").write_text("Content.\n", encoding="utf-8")
            vault_root = root / "vault_is_a_file"
            vault_root.write_text("", encoding="utf-8")

            old_argv = sys.argv
            sys.argv = [
                "sync_vault",
                "--journal-root", str(journal_root),
                "--vault-root", str(vault_root),
                "--date", "2026-08-28",
            ]
            try:
                exit_code = main()
            finally:
                sys.argv = old_argv

            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
