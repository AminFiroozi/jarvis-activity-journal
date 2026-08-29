import tempfile
import unittest
from pathlib import Path

from src.orchestration.vault_linker import build_name_index, build_note_paths, inject_links


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

    def test_inject_links_omits_alias_when_word_matches_base_name_exactly(self):
        index = {"docker": ["Docker"]}

        result = inject_links("Docker is great.", index)

        self.assertEqual(result, "[[Docker]] is great.")

    def test_inject_links_keeps_alias_when_word_differs_from_base_name(self):
        index = {"dariush": ["DariushSeif"]}

        result = inject_links("dariush called.", index)

        self.assertEqual(result, "[[DariushSeif|dariush]] called.")

    def test_build_name_index_keeps_multiword_stem_as_single_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills = root / "Skills"
            skills.mkdir()
            (skills / "Data Structure and Algorithms.md").write_text("", encoding="utf-8")

            index = build_name_index(root)

            self.assertEqual(
                index["data structure and algorithms"],
                ["Data Structure and Algorithms"],
            )
            self.assertIsNone(index.get("and"))
            self.assertIsNone(index.get("data"))

    def test_build_name_index_keeps_hyphenated_stem_as_single_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projects = root / "Projects"
            projects.mkdir()
            (projects / "HW1-notebook-grading.md").write_text("", encoding="utf-8")

            index = build_name_index(root)

            self.assertEqual(index["hw1-notebook-grading"], ["HW1-notebook-grading"])
            self.assertIsNone(index.get("notebook"))

    def test_build_name_index_keeps_underscored_stem_as_single_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projects = root / "Projects"
            projects.mkdir()
            (projects / "Mahoura_Frontend_Index.md").write_text("", encoding="utf-8")

            index = build_name_index(root)

            self.assertEqual(index["mahoura_frontend_index"], ["Mahoura_Frontend_Index"])
            self.assertIsNone(index.get("index"))

    def test_build_name_index_drops_short_pascal_case_fragments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projects = root / "Projects"
            projects.mkdir()
            (projects / "BargheNo.md").write_text("", encoding="utf-8")

            index = build_name_index(root)

            self.assertEqual(index["barghe"], ["BargheNo"])
            self.assertEqual(index["bargheno"], ["BargheNo"])
            self.assertIsNone(index.get("no"))

    def test_build_name_index_skips_people_history_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "People" / "History"
            history.mkdir(parents=True)
            (history / "SomeName - 2025-01.md").write_text("", encoding="utf-8")
            friends = root / "People" / "Friends"
            friends.mkdir(parents=True)
            (friends / "SomeName.md").write_text("", encoding="utf-8")

            index = build_name_index(root)

            all_names = [name for names in index.values() for name in names]
            self.assertNotIn("SomeName - 2025-01", all_names)
            self.assertIn("SomeName", index["somename"])

    def test_build_note_paths_maps_stem_to_real_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_vault(root)

            note_paths = build_note_paths(root)

            self.assertEqual([path.stem for path in note_paths["DariushSeif"]], ["DariushSeif"])
            self.assertTrue(note_paths["DariushSeif"][0].exists())

    def test_build_note_paths_excludes_companion_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_vault(root)
            (root / "People" / "Friends" / "DariushSeif - Activity Mentions.md").write_text("", encoding="utf-8")
            (root / "Projects" / "Mahoura - Activity Log.md").write_text("", encoding="utf-8")

            note_paths = build_note_paths(root)
            index = build_name_index(root)

            self.assertNotIn("DariushSeif - Activity Mentions", note_paths)
            self.assertNotIn("Mahoura - Activity Log", note_paths)
            self.assertNotIn("mentions", index)


if __name__ == "__main__":
    unittest.main()
