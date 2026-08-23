import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from synthesize_journal import parse_model_json, upsert_narrative


class SynthesisTests(unittest.TestCase):
    def test_parse_model_json_accepts_fenced_json(self):
        result = parse_model_json('```json\n{"summary":"Worked on Jarvis","confidence":0.9}\n```')
        self.assertEqual(result["summary"], "Worked on Jarvis")

    def test_upsert_narrative_replaces_existing_section(self):
        original = "# Daily Journal\n\n## Applications\n\n- PowerShell\n\n## LLM narrative\n\nOld text\n"
        updated = upsert_narrative(original, {"summary": "Worked on the journal pipeline", "confidence": 0.8})
        self.assertEqual(updated.count("## LLM narrative"), 1)
        self.assertIn("Worked on the journal pipeline", updated)
        self.assertNotIn("Old text", updated)


if __name__ == "__main__":
    unittest.main()
