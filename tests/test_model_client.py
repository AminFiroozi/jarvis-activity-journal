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

    def test_resolves_optional_proxy(self):
        config = {
            "providers": {
                "cloud-vision-groq": {"endpoint": "https://api.groq.com/openai/v1/chat/completions", "model": "m", "proxy": "http://127.0.0.1:10808"}
            },
            "screenshotAnalyzer": {"activeProvider": "cloud-vision-groq"},
        }
        provider = resolve_provider(config, "screenshotAnalyzer")
        self.assertEqual(provider["proxy"], "http://127.0.0.1:10808")

    def test_proxy_defaults_to_none(self):
        config = {
            "providers": {"local-vision": {"endpoint": "http://localhost:1234/v1/chat/completions", "model": "m"}},
            "screenshotAnalyzer": {"activeProvider": "local-vision"},
        }
        provider = resolve_provider(config, "screenshotAnalyzer")
        self.assertIsNone(provider["proxy"])

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
