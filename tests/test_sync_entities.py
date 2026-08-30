import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.orchestration.sync_entities import (
    append_entry,
    companion_path,
    main,
    resolve_note_name,
    sync_entities,
)
from src.orchestration.vault_linker import build_name_index, build_note_paths


def _write_narrative(journal_root: Path, date: str) -> None:
    raw = journal_root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"journal-{date}.json").write_text(
        json.dumps({"summary": "A day of ordinary activity was observed."}),
        encoding="utf-8",
    )


def _make_vault(root: Path) -> None:
    friends = root / "People" / "Friends"
    friends.mkdir(parents=True)
    (friends / "DariushSeif.md").write_text("curated content\n", encoding="utf-8")
    (friends / "ErfanMoayed.md").write_text("", encoding="utf-8")
    (friends / "ErfanTajik.md").write_text("", encoding="utf-8")
    projects = root / "Projects"
    projects.mkdir()
    (projects / "Mahoura.md").write_text("curated content\n", encoding="utf-8")
    skills = root / "Skills"
    skills.mkdir()
    (skills / "Python.md").write_text("", encoding="utf-8")


class ResolveNoteNameTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        _make_vault(self.root)
        self.index = build_name_index(self.root)
        self.note_paths = build_note_paths(self.root)

    def tearDown(self):
        self.directory.cleanup()

    def test_resolves_exact_stem(self):
        result = resolve_note_name("DariushSeif", self.index, self.note_paths, "people", self.root)
        self.assertEqual(result.stem, "DariushSeif")

    def test_resolves_single_token(self):
        result = resolve_note_name("Dariush", self.index, self.note_paths, "people", self.root)
        self.assertEqual(result.stem, "DariushSeif")

    def test_resolves_separator_stripped_name(self):
        result = resolve_note_name("Dariush Seif", self.index, self.note_paths, "people", self.root)
        self.assertEqual(result.stem, "DariushSeif")

    def test_drops_ambiguous_shared_first_name(self):
        result = resolve_note_name("Erfan", self.index, self.note_paths, "people", self.root)
        self.assertIsNone(result)

    def test_drops_unknown_name(self):
        result = resolve_note_name("SomeoneNotInTheVault", self.index, self.note_paths, "people", self.root)
        self.assertIsNone(result)

    def test_drops_category_mismatch(self):
        result = resolve_note_name("Python", self.index, self.note_paths, "projects", self.root)
        self.assertIsNone(result)

    def test_person_never_resolves_under_projects(self):
        result = resolve_note_name("Mahoura", self.index, self.note_paths, "people", self.root)
        self.assertIsNone(result)

    def test_drops_case_insensitive_stem_collision_across_subdirectories(self):
        (self.root / "People" / "Friends" / "Kian.md").write_text("", encoding="utf-8")
        uni = self.root / "People" / "Uni"
        uni.mkdir()
        (uni / "kian.md").write_text("", encoding="utf-8")
        index = build_name_index(self.root)
        note_paths = build_note_paths(self.root)
        result = resolve_note_name("kian", index, note_paths, "people", self.root)
        self.assertIsNone(result)


class CategoryGateAncestorDirectoryTests(unittest.TestCase):
    def test_vault_under_a_projects_named_ancestor_does_not_leak_category(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory) / "Projects" / "vault"
            _make_vault(vault_root)
            index = build_name_index(vault_root)
            note_paths = build_note_paths(vault_root)
            result = resolve_note_name("Python", index, note_paths, "projects", vault_root)
            self.assertIsNone(result)
            result = resolve_note_name("Mahoura", index, note_paths, "projects", vault_root)
            self.assertEqual(result.stem, "Mahoura")

    def test_vault_under_a_people_named_ancestor_does_not_leak_category(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory) / "People" / "vault"
            _make_vault(vault_root)
            index = build_name_index(vault_root)
            note_paths = build_note_paths(vault_root)
            result = resolve_note_name("Python", index, note_paths, "people", vault_root)
            self.assertIsNone(result)
            result = resolve_note_name("DariushSeif", index, note_paths, "people", vault_root)
            self.assertEqual(result.stem, "DariushSeif")


class CompanionPathTests(unittest.TestCase):
    def test_person_companion_lives_beside_the_curated_note(self):
        note_path = Path("/vault/People/Friends/DariushSeif.md")
        result = companion_path(note_path, "people")
        self.assertEqual(result, Path("/vault/People/Friends/DariushSeif - Activity Mentions.md"))

    def test_project_companion_lives_beside_the_curated_note(self):
        note_path = Path("/vault/Projects/Mahoura.md")
        result = companion_path(note_path, "projects")
        self.assertEqual(result, Path("/vault/Projects/Mahoura - Activity Log.md"))


class AppendEntryTests(unittest.TestCase):
    def test_creates_file_with_header_and_backlink_on_first_write(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "DariushSeif - Activity Mentions.md"
            result = append_entry(target, "DariushSeif", "people", "2026-08-23", "## 2026-08-23\n\nSome note.\n")
            self.assertEqual(result, target)
            content = target.read_text(encoding="utf-8")
            self.assertIn("[[DariushSeif]]", content)
            self.assertIn("## 2026-08-23", content)

    def test_second_date_appends_a_second_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "DariushSeif - Activity Mentions.md"
            append_entry(target, "DariushSeif", "people", "2026-08-23", "## 2026-08-23\n\nFirst.\n")
            append_entry(target, "DariushSeif", "people", "2026-08-24", "## 2026-08-24\n\nSecond.\n")
            content = target.read_text(encoding="utf-8")
            self.assertIn("## 2026-08-23", content)
            self.assertIn("## 2026-08-24", content)

    def test_rerunning_the_same_date_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "DariushSeif - Activity Mentions.md"
            append_entry(target, "DariushSeif", "people", "2026-08-23", "## 2026-08-23\n\nFirst.\n")
            before = target.read_text(encoding="utf-8")
            second_result = append_entry(target, "DariushSeif", "people", "2026-08-23", "## 2026-08-23\n\nDifferent text.\n")
            after = target.read_text(encoding="utf-8")
            self.assertIsNone(second_result)
            self.assertEqual(before, after)


class SyncEntitiesTests(unittest.TestCase):
    def _config(self, **overrides):
        base = {"entityUpdates": {"enabled": True, "activeProvider": "test-provider", "minConfidence": 0.0, "maxEntitiesPerDay": 5}, "providers": {"test-provider": {"endpoint": "http://x", "model": "m"}}}
        base["entityUpdates"].update(overrides)
        return base

    def test_disabled_by_default_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            result = sync_entities(journal, vault, {"entityUpdates": {"enabled": False}}, "2026-08-23")
            self.assertEqual(result["status"], "disabled")
            self.assertFalse((vault / "People" / "Friends" / "DariushSeif - Activity Mentions.md").exists())

    def test_invalid_date_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = sync_entities(root / "journal", root / "vault", self._config(), "../../escaped")
            self.assertEqual(result["status"], "invalid-date")

    def test_end_to_end_writes_companion_note_and_leaves_curated_note_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            _write_narrative(journal, "2026-08-23")
            curated_before = (vault / "People" / "Friends" / "DariushSeif.md").read_text(encoding="utf-8")

            canned = json.dumps({
                "people": [{"name": "DariushSeif", "note": "Dariush reviewed a pull request on the Mahoura project today.", "evidence": ["reviewed PR"], "confidence": 0.8}],
                "projects": [],
            })
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(), "2026-08-23")

            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(result["written"]), 1)
            companion = vault / "People" / "Friends" / "DariushSeif - Activity Mentions.md"
            self.assertTrue(companion.exists())
            self.assertIn("reviewed a pull request", companion.read_text(encoding="utf-8"))
            self.assertIn("[[Mahoura]]", companion.read_text(encoding="utf-8"))
            curated_after = (vault / "People" / "Friends" / "DariushSeif.md").read_text(encoding="utf-8")
            self.assertEqual(curated_before, curated_after)

    def test_ambiguous_name_is_skipped_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            _write_narrative(journal, "2026-08-23")
            canned = json.dumps({"people": [{"name": "Erfan", "note": "x" * 50, "confidence": 0.9}], "projects": []})
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(), "2026-08-23")
            self.assertEqual(result["written"], [])
            self.assertEqual(result["skipped"][0]["reason"], "unresolved-or-ambiguous")

    def test_max_entities_per_day_caps_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            _write_narrative(journal, "2026-08-23")
            (vault / "People" / "Friends" / "AnotherPerson.md").write_text("", encoding="utf-8")
            canned = json.dumps({
                "people": [
                    {"name": "DariushSeif", "note": "x" * 50, "confidence": 0.9},
                    {"name": "AnotherPerson", "note": "y" * 50, "confidence": 0.5},
                ],
                "projects": [],
            })
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(maxEntitiesPerDay=1), "2026-08-23")
            self.assertEqual(len(result["written"]), 1)
            self.assertEqual(result["written"][0]["name"], "DariushSeif")

    def test_dry_run_writes_status_but_nothing_under_the_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            _write_narrative(journal, "2026-08-23")
            canned = json.dumps({"people": [{"name": "DariushSeif", "note": "x" * 50, "confidence": 0.9}], "projects": []})
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(), "2026-08-23", dry_run=True)
            self.assertEqual(len(result["written"]), 1)
            self.assertFalse((vault / "People" / "Friends" / "DariushSeif - Activity Mentions.md").exists())

    def test_zero_evidence_day_never_calls_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            with mock.patch("src.analysis.entity_facts.call_chat_completions") as mocked:
                result = sync_entities(journal, vault, self._config(), "2026-08-23")
            mocked.assert_not_called()
            self.assertEqual(result["status"], "no-events")
            self.assertEqual(result["written"], [])
            self.assertEqual(result["skipped"], [])
            self.assertFalse((vault / "People" / "Friends" / "DariushSeif - Activity Mentions.md").exists())
            self.assertFalse((vault / "Projects" / "Mahoura - Activity Log.md").exists())

    def test_empty_roster_day_never_calls_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            vault.mkdir()
            _write_narrative(journal, "2026-08-23")
            with mock.patch("src.analysis.entity_facts.call_chat_completions") as mocked:
                result = sync_entities(journal, vault, self._config(), "2026-08-23")
            mocked.assert_not_called()
            self.assertEqual(result["status"], "no-events")
            self.assertEqual(result["written"], [])
            self.assertEqual(result["skipped"], [])

    def test_malformed_model_response_writes_failed_status_with_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            _write_narrative(journal, "2026-08-23")
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value="not json at all"):
                result = sync_entities(journal, vault, self._config(), "2026-08-23")
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result.get("error"))
            status_path = journal / "raw" / "entities-2026-08-23.status.json"
            self.assertTrue(status_path.exists())
            on_disk = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["status"], "failed")
            self.assertTrue(on_disk.get("error"))

    def test_confidence_dedup_loser_is_recorded_in_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            _write_narrative(journal, "2026-08-23")
            canned = json.dumps({
                "people": [
                    {"name": "DariushSeif", "note": "a" * 50, "confidence": 0.4},
                    {"name": "Dariush", "note": "b" * 50, "confidence": 0.9},
                ],
                "projects": [],
            })
            with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                result = sync_entities(journal, vault, self._config(), "2026-08-23")
            self.assertEqual(len(result["written"]), 1)
            self.assertEqual(result["written"][0]["name"], "DariushSeif")
            superseded = [entry for entry in result["skipped"] if entry["reason"] == "superseded-by-higher-confidence"]
            self.assertEqual(len(superseded), 1)
            self.assertEqual(superseded[0]["name"], "DariushSeif")


class MainTests(unittest.TestCase):
    def test_main_exits_zero_on_malformed_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            vault.mkdir()
            config_path = root / "settings.json"
            config_path.write_text("not valid json", encoding="utf-8")
            old_argv = sys.argv
            sys.argv = ["sync_entities", "--journal-root", str(journal), "--config", str(config_path), "--vault-root", str(vault), "--date", "2026-08-23"]
            try:
                exit_code = main()
            finally:
                sys.argv = old_argv
            self.assertEqual(exit_code, 0)

    def test_main_exits_zero_when_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            vault.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({"entityUpdates": {"enabled": False}}), encoding="utf-8")
            old_argv = sys.argv
            sys.argv = ["sync_entities", "--journal-root", str(journal), "--config", str(config_path), "--vault-root", str(vault), "--date", "2026-08-23"]
            try:
                exit_code = main()
            finally:
                sys.argv = old_argv
            self.assertEqual(exit_code, 0)

    def test_main_exits_zero_when_heartbeat_write_itself_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.write_text("not a directory", encoding="utf-8")
            vault = root / "vault"
            vault.mkdir()
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({
                "entityUpdates": {"enabled": True, "activeProvider": "test-provider"},
                "providers": {"test-provider": {"endpoint": "http://x", "model": "m"}},
            }), encoding="utf-8")
            old_argv = sys.argv
            sys.argv = ["sync_entities", "--journal-root", str(journal), "--config", str(config_path), "--vault-root", str(vault), "--date", "2026-08-23"]
            canned = json.dumps({"people": [], "projects": []})
            try:
                with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned):
                    exit_code = main()
            finally:
                sys.argv = old_argv
            self.assertEqual(exit_code, 0)

    def test_main_writes_failure_heartbeat_on_malformed_model_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            vault = root / "vault"
            journal.mkdir()
            _make_vault(vault)
            _write_narrative(journal, "2026-08-23")
            config_path = root / "settings.json"
            config_path.write_text(json.dumps({
                "entityUpdates": {"enabled": True, "activeProvider": "test-provider"},
                "providers": {"test-provider": {"endpoint": "http://x", "model": "m"}},
            }), encoding="utf-8")
            old_argv = sys.argv
            sys.argv = ["sync_entities", "--journal-root", str(journal), "--config", str(config_path), "--vault-root", str(vault), "--date", "2026-08-23"]
            try:
                with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value="not json at all"):
                    exit_code = main()
            finally:
                sys.argv = old_argv
            self.assertEqual(exit_code, 0)
            heartbeat_path = journal / "health" / "entity-updates.json"
            self.assertTrue(heartbeat_path.exists())
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "failed")
            self.assertTrue(heartbeat.get("lastError"))


if __name__ == "__main__":
    unittest.main()
