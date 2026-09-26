import unittest

from src.analysis.report_levels import LEVELS, build_prompt


class BuildPromptTests(unittest.TestCase):
    def test_all_levels_share_the_same_json_shape(self):
        for level in LEVELS:
            prompt = build_prompt(level)
            for key in ('"summary"', '"on_screen"', '"timeline"', '"patterns"', '"next_actions"'):
                self.assertIn(key, prompt)

    def test_no_level_asks_for_confidence(self):
        for level in LEVELS:
            self.assertNotIn("confidence", build_prompt(level).lower())

    def test_levels_differ_in_depth_and_source(self):
        hourly, daily, weekly = (build_prompt(level) for level in LEVELS)

        self.assertIn("one hour", hourly)
        self.assertIn("every distinct screen", hourly)
        self.assertIn("one day", daily)
        self.assertIn("hourly reports", daily)
        self.assertIn("one week", weekly)
        self.assertIn("daily reports", weekly)
        self.assertEqual(len({hourly, daily, weekly}), 3)

    def test_privacy_and_readability_rules_are_stated(self):
        prompt = build_prompt("hourly")

        self.assertIn("never quote message text", prompt)
        self.assertIn("local times", prompt)

    def test_unknown_level_raises(self):
        with self.assertRaises(KeyError):
            build_prompt("monthly")


if __name__ == "__main__":
    unittest.main()
