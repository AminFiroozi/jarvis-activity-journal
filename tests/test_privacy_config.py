import unittest

from src.privacy_config import DEFAULT_PRIVACY_CONFIG, load_privacy_config


class PrivacyConfigTests(unittest.TestCase):
    def test_missing_privacy_block_resolves_to_safe_defaults(self):
        result = load_privacy_config({})

        self.assertEqual(result, DEFAULT_PRIVACY_CONFIG)
        self.assertTrue(result["captureEnabled"])
        self.assertEqual(result["retentionDays"], 14)
        self.assertTrue(result["redactBeforeStorage"])

    def test_partial_privacy_block_merges_with_defaults(self):
        result = load_privacy_config({"privacy": {"retentionDays": 30}})

        self.assertEqual(result["retentionDays"], 30)
        self.assertEqual(result["excludedApplications"], [])
        self.assertTrue(result["redactBeforeStorage"])

    def test_invalid_retention_is_rejected(self):
        with self.assertRaises(ValueError):
            load_privacy_config({"privacy": {"retentionDays": 0}})

        with self.assertRaises(ValueError):
            load_privacy_config({"privacy": {"retentionDays": "14"}})


if __name__ == "__main__":
    unittest.main()
