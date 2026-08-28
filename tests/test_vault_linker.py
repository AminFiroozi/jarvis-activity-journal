import tempfile
import unittest
from pathlib import Path

from src.orchestration.vault_linker import build_name_index, inject_links


class VaultLinkerTests(unittest.TestCase):
    def _make_vault(self, root: Path) -> None:
        friends = root / "People" / "Friends"
        friends.mkdir(parents=True)
        (friends / "DariushSeif.md").write_text("", encoding="utf-8")
        (friends / "AlirezaRahimi.md").write_text("", encoding="utf-8")
        (friends / "AlirezaKarimi.md").write_text("", encoding="utf-8")
        projects = root / "Projects"
        projects.mkdir()
        (projects / "Mahoura.md").write_text("", encoding="utf-8")

    def test_build_name_index_splits_pascal_case_filenames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_vault(root)

            index = build_name_index(root)

            self.assertEqual(index["dariush"], ["DariushSeif"])
            self.assertEqual(index["seif"], ["DariushSeif"])
            self.assertEqual(index["dariushseif"], ["DariushSeif"])
            self.assertEqual(index["mahoura"], ["Mahoura"])

    def test_build_name_index_flags_ambiguous_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_vault(root)

            index = build_name_index(root)

            self.assertCountEqual(index["alireza"], ["AlirezaRahimi", "AlirezaKarimi"])
            self.assertEqual(index["rahimi"], ["AlirezaRahimi"])

    def test_inject_links_wraps_single_match_with_alias(self):
        index = {"dariush": ["DariushSeif"]}

        result = inject_links("Chatted with Dariush about the project.", index)

        self.assertEqual(result, "Chatted with [[DariushSeif|Dariush]] about the project.")

    def test_inject_links_skips_ambiguous_tokens(self):
        index = {"alireza": ["AlirezaRahimi", "AlirezaKarimi"]}

        result = inject_links("Met Alireza today.", index)

        self.assertEqual(result, "Met Alireza today.")

    def test_inject_links_does_not_mangle_already_bracketed_text(self):
        index = {"dariush": ["DariushSeif"]}

        result = inject_links("[[DariushSeif|Dariush]] again about Dariush.", index)

        self.assertEqual(result, "[[DariushSeif|Dariush]] again about [[DariushSeif|Dariush]].")

    def test_inject_links_is_case_insensitive(self):
        index = {"dariush": ["DariushSeif"]}

        result = inject_links("DARIUSH called.", index)

        self.assertEqual(result, "[[DariushSeif|DARIUSH]] called.")


if __name__ == "__main__":
    unittest.main()
