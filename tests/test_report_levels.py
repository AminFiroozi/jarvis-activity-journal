import unittest

from src.analysis.report_levels import LEVELS, build_prompt


class BuildPromptTests(unittest.TestCase):
    def test_all_levels_share_the_same_json_shape(self):
        for level in LEVELS:
            prompt = build_prompt(level)
            for key in ('"summary"', '"timeline"', '"patterns"'):
                self.assertIn(key, prompt)
            self.assertNotIn('"on_screen"', build_prompt(level))
            self.assertNotIn("On screen", build_prompt(level))

    def test_prompt_asks_for_analysis_only_and_has_no_next_actions(self):
        for level in LEVELS:
            prompt = build_prompt(level)
            self.assertNotIn("next_actions", prompt)
            self.assertNotIn("next actions", prompt.lower())
            self.assertIn("analysis only", prompt)

    def test_no_level_asks_for_confidence(self):
        for level in LEVELS:
            self.assertNotIn("confidence", build_prompt(level).lower())

    def test_levels_differ_in_depth_and_source(self):
        hourly, daily, weekly = (build_prompt(level) for level in LEVELS)

        self.assertIn("one hour", hourly)
        self.assertIn("concrete names", hourly)
        self.assertIn("one day", daily)
        self.assertIn("hourly reports", daily)
        self.assertIn("one week", weekly)
        self.assertIn("daily reports", weekly)
        self.assertIn("longer and richer than an hourly report", daily)
        self.assertIn("longer than a daily report", weekly)
        self.assertEqual(len({hourly, daily, weekly}), 3)

    def test_privacy_and_readability_rules_are_stated(self):
        prompt = build_prompt("hourly")

        self.assertIn("never quote message text", prompt)
        self.assertIn("local times", prompt)

    def test_prompts_keep_chat_specifics_without_quoting(self):
        for level in LEVELS:
            prompt = build_prompt(level)
            self.assertIn("correspondent", prompt)
            self.assertIn("never quoting message text", prompt)

    def test_format_version_is_four(self):
        from src.analysis.report_levels import REPORT_FORMAT_VERSION

        self.assertEqual(REPORT_FORMAT_VERSION, "4")

    def test_unknown_level_raises(self):
        with self.assertRaises(KeyError):
            build_prompt("monthly")


if __name__ == "__main__":
    unittest.main()
