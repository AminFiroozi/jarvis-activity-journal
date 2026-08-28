import json
import tempfile
import unittest
from pathlib import Path

from src.analysis.analyze_screenshots import build_prompt, load_prompts, select_prompt_context
from src.analysis.ocr import extract_text


class VisionPromptTests(unittest.TestCase):
    def test_each_application_context_selects_distinct_instructions(self):
        prompts = load_prompts(Path(__file__).parents[1] / "config" / "prompts.json")

        selected = {
            context: select_prompt_context(context, prompts)["instructions"]
            for context in ("terminal", "browser", "ide", "messaging", "unknown")
        }

        self.assertEqual(len(set(selected.values())), 5)
        for instructions in selected.values():
            self.assertIn("observed", instructions.lower())
            self.assertIn("secret", instructions.lower())

    def test_prompt_includes_ocr_regions_and_fact_only_contract(self):
        prompts = load_prompts(Path(__file__).parents[1] / "config" / "prompts.json")

        prompt = build_prompt(
            "terminal",
            prompts,
            {"available": True, "regions": [{"text": "pytest passed", "confidence": 0.98, "box": [1, 2, 3, 4]}]},
        )

        self.assertIn("pytest passed", prompt)
        self.assertIn("observed facts", prompt.lower())
        self.assertIn("do not include secrets", prompt.lower())

    def test_ocr_missing_optional_dependency_is_failure_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "screen.jpg"
            image.write_bytes(b"not-an-image")

            result = extract_text(image, ocr_module=None)

        self.assertFalse(result["available"])
        self.assertEqual(result["regions"], [])
        self.assertIn("unavailable", result["reason"])

    def test_ocr_returns_normalized_regions_with_confidence_and_box(self):
        class FakeOutput:
            DICT = "dict"

        class FakeOcr:
            Output = FakeOutput

            @staticmethod
            def image_to_data(_image, output_type):
                self.assertEqual(output_type, "dict")
                return {"text": ["build", ""], "conf": ["80", "-1"], "left": [4, 0], "top": [5, 0], "width": [20, 0], "height": [10, 0]}

        with tempfile.TemporaryDirectory() as directory:
            result = extract_text(Path(directory) / "screen.jpg", ocr_module=FakeOcr)

        self.assertTrue(result["available"])
        self.assertEqual(result["regions"], [{"text": "build", "confidence": 0.8, "box": [4, 5, 20, 10]}])


if __name__ == "__main__":
    unittest.main()
