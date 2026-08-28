import json
import tempfile
import unittest
from pathlib import Path

from src.build_llm_context import render


class RenderLlmContextTests(unittest.TestCase):
    def test_no_activity_file_returns_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            text = render(Path(directory), "2026-01-01")
            self.assertIn("No local activity events found", text)

    def test_includes_observed_applications_and_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            event = {
                "source": "foreground-window",
                "process": "chrome",
                "windowTitle": "Example",
                "localTimestamp": "2026-01-01T10:00:00+00:00",
                "active": True,
            }
            (raw / "activity-2026-01-01.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

            text = render(root, "2026-01-01")

            self.assertIn("chrome: 1 samples", text)
            self.assertIn("Example", text)


if __name__ == "__main__":
    unittest.main()
