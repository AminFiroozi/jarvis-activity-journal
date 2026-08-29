import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analysis.entity_facts import (
    build_evidence,
    compact_entity_event,
    extract_entity_facts,
    summarize_projects,
    validate_facts,
)


class CompactEntityEventTests(unittest.TestCase):
    def test_compacts_git_project_events(self):
        event = {
            "source": "git-project",
            "projectPath": "/repo/mahoura",
            "branch": "main",
            "latestCommit": "abc123",
            "latestCommitMessage": "fix bug",
            "changedFileCount": 3,
            "timestamp": "2026-08-23T10:00:00+00:00",
        }
        result = compact_entity_event(event)
        self.assertEqual(result["type"], "project")
        self.assertEqual(result["path"], "/repo/mahoura")
        self.assertEqual(result["commit"], "abc123")

    def test_delegates_other_sources_to_narrative_compact_event(self):
        event = {"source": "foreground-window", "process": "Code", "timestamp": "2026-08-23T10:00:00+00:00"}
        result = compact_entity_event(event)
        self.assertEqual(result["type"], "window")


class SummarizeProjectsTests(unittest.TestCase):
    def test_collapses_repeated_snapshots_into_one_record_per_path(self):
        events = [
            {"type": "project", "path": "/repo/mahoura", "branch": "main", "commit": "abc123", "message": "fix bug", "changedFileCount": 2},
            {"type": "project", "path": "/repo/mahoura", "branch": "main", "commit": "abc123", "message": "fix bug", "changedFileCount": 5},
            {"type": "project", "path": "/repo/mahoura", "branch": "main", "commit": "def456", "message": "add feature", "changedFileCount": 1},
            {"type": "window", "app": "Code"},
        ]
        result = summarize_projects(events)
        self.assertEqual(len(result), 1)
        record = result[0]
        self.assertEqual(record["path"], "/repo/mahoura")
        self.assertEqual(record["name"], "mahoura")
        self.assertEqual(record["maxChangedFileCount"], 5)
        self.assertEqual([c["hash"] for c in record["commits"]], ["abc123", "def456"])

    def test_empty_events_produce_empty_list(self):
        self.assertEqual(summarize_projects([]), [])


class BuildEvidenceTests(unittest.TestCase):
    def test_prefers_the_synthesized_narrative_json(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "raw").mkdir()
            (journal / "raw" / "journal-2026-08-23.json").write_text(json.dumps({"summary": "Worked on Mahoura with Dariush."}), encoding="utf-8")

            evidence = build_evidence(journal, "2026-08-23", roster={"people": ["DariushSeif"], "projects": ["Mahoura"]})

            self.assertEqual(evidence["narrative"], "Worked on Mahoura with Dariush.")
            self.assertEqual(evidence["roster"]["people"], ["DariushSeif"])

    def test_falls_back_to_daily_markdown_narrative_section(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            (journal / "daily").mkdir()
            (journal / "daily" / "2026-08-23.md").write_text("# Journal\n\n## LLM narrative\n\nWorked on Mahoura.\n", encoding="utf-8")

            evidence = build_evidence(journal, "2026-08-23", roster={"people": [], "projects": []})

            self.assertIn("Worked on Mahoura.", evidence["narrative"])

    def test_narrative_is_none_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = build_evidence(Path(directory), "2026-08-23", roster={"people": [], "projects": []})
            self.assertIsNone(evidence["narrative"])


class ExtractEntityFactsTests(unittest.TestCase):
    def test_parses_the_model_response(self):
        provider = {"name": "test"}
        evidence = {"date": "2026-08-23", "narrative": "text", "projects": [], "roster": {"people": [], "projects": []}, "events": []}
        canned = json.dumps({"people": [{"name": "DariushSeif", "note": "x" * 50, "confidence": 0.8}], "projects": []})
        with mock.patch("src.analysis.entity_facts.call_chat_completions", return_value=canned) as mocked:
            result = extract_entity_facts(provider, evidence)
        self.assertEqual(result["people"][0]["name"], "DariushSeif")
        mocked.assert_called_once()


class ValidateFactsTests(unittest.TestCase):
    def test_drops_entries_with_blank_name_or_short_note(self):
        payload = {
            "people": [{"name": "", "note": "x" * 50}, {"name": "DariushSeif", "note": "too short"}, {"name": "Mahoura", "note": "x" * 50, "confidence": 0.7}],
            "projects": "not-a-list",
        }
        result = validate_facts(payload)
        self.assertEqual(len(result["people"]), 1)
        self.assertEqual(result["people"][0]["name"], "Mahoura")
        self.assertEqual(result["projects"], [])

    def test_defaults_confidence_and_evidence(self):
        payload = {"people": [{"name": "X", "note": "y" * 50}], "projects": []}
        result = validate_facts(payload)
        self.assertEqual(result["people"][0]["confidence"], 0.0)
        self.assertEqual(result["people"][0]["evidence"], [])


if __name__ == "__main__":
    unittest.main()
