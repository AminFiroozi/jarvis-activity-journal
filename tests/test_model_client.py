import unittest

from src.model_client import ProviderError, resolve_provider


class ResolveProviderTests(unittest.TestCase):
    def test_resolves_named_provider(self):
        config = {
            "providers": {
                "local-vision": {"endpoint": "http://localhost:1234/v1/chat/completions", "model": "m", "apiKeyEnv": "VISION_API_KEY"}
            },
            "screenshotAnalyzer": {"activeProvider": "local-vision"},
        }
        provider = resolve_provider(config, "screenshotAnalyzer")
        self.assertEqual(provider["endpoint"], "http://localhost:1234/v1/chat/completions")
        self.assertEqual(provider["model"], "m")
        self.assertEqual(provider["name"], "local-vision")

    def test_missing_active_provider_raises(self):
        config = {"providers": {}, "screenshotAnalyzer": {}}
        with self.assertRaises(ProviderError):
            resolve_provider(config, "screenshotAnalyzer")

    def test_undefined_provider_name_raises(self):
        config = {"providers": {}, "screenshotAnalyzer": {"activeProvider": "ghost"}}
        with self.assertRaises(ProviderError):
            resolve_provider(config, "screenshotAnalyzer")


if __name__ == "__main__":
    unittest.main()
