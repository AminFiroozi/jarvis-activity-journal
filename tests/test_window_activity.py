import unittest

from src.window_activity import redact_title


class RedactTitleTests(unittest.TestCase):
    def test_redacts_on_pattern_match(self):
        result = redact_title("my password: hunter2", [r"password"], 180)
        self.assertEqual(result, "[redacted window title]")

    def test_truncates_long_titles(self):
        result = redact_title("x" * 200, [], 10)
        self.assertEqual(result, "x" * 10 + "…")

    def test_none_title_passes_through(self):
        self.assertIsNone(redact_title(None, [r"password"], 180))


if __name__ == "__main__":
    unittest.main()
