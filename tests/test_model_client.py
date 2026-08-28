import json
import os
import unittest
from unittest import mock

from src.model_client import ProviderError, call_chat_completions, resolve_provider


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

    def test_single_api_key_env_resolves_to_one_key_list(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "key-a"}):
            config = {
                "providers": {"g": {"endpoint": "e", "model": "m", "apiKeyEnv": "GROQ_API_KEY"}},
                "screenshotAnalyzer": {"activeProvider": "g"},
            }
            provider = resolve_provider(config, "screenshotAnalyzer")
            self.assertEqual(provider["api_keys"], ["key-a"])

    def test_multiple_api_key_envs_collects_only_set_ones(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "key-a", "GROQ_API_KEY_3": "key-c"}, clear=False):
            os.environ.pop("GROQ_API_KEY_2", None)
            config = {
                "providers": {"g": {"endpoint": "e", "model": "m", "apiKeyEnv": ["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"]}},
                "screenshotAnalyzer": {"activeProvider": "g"},
            }
            provider = resolve_provider(config, "screenshotAnalyzer")
            self.assertEqual(provider["api_keys"], ["key-a", "key-c"])

    def test_no_api_key_env_resolves_to_empty_list(self):
        config = {"providers": {"g": {"endpoint": "e", "model": "m"}}, "screenshotAnalyzer": {"activeProvider": "g"}}
        provider = resolve_provider(config, "screenshotAnalyzer")
        self.assertEqual(provider["api_keys"], [])


class CallChatCompletionsRotationTests(unittest.TestCase):
    def test_rotates_to_next_key_on_429_without_sleeping(self):
        provider = {"name": "g", "endpoint": "https://example.invalid", "model": "m", "api_keys": ["key-a", "key-b"], "extra_headers": {}, "proxy": None}
        used_keys = []

        def fake_open(request, timeout=None):
            used_keys.append(request.get_header("Authorization"))
            if len(used_keys) == 1:
                raise self._http_error(429)
            return self._fake_response({"choices": [{"message": {"content": "ok"}}]})

        with mock.patch("src.model_client.urllib.request.urlopen", side_effect=fake_open), mock.patch("src.model_client.time.sleep") as sleep_mock:
            result = call_chat_completions(provider, [{"role": "user", "content": "hi"}])

        self.assertEqual(result, "ok")
        self.assertEqual(used_keys, ["Bearer key-a", "Bearer key-b"])
        sleep_mock.assert_not_called()

    def test_sleeps_only_after_cycling_through_all_keys(self):
        provider = {"name": "g", "endpoint": "https://example.invalid", "model": "m", "api_keys": ["key-a", "key-b"], "extra_headers": {}, "proxy": None}
        calls = []

        def fake_open(request, timeout=None):
            calls.append(request.get_header("Authorization"))
            if len(calls) <= 2:
                raise self._http_error(429)
            return self._fake_response({"choices": [{"message": {"content": "ok"}}]})

        with mock.patch("src.model_client.urllib.request.urlopen", side_effect=fake_open), mock.patch("src.model_client.time.sleep") as sleep_mock:
            result = call_chat_completions(provider, [{"role": "user", "content": "hi"}])

        self.assertEqual(result, "ok")
        self.assertEqual(calls, ["Bearer key-a", "Bearer key-b", "Bearer key-a"])
        sleep_mock.assert_called_once()

    @staticmethod
    def _http_error(code):
        import urllib.error

        return urllib.error.HTTPError("https://example.invalid", code, "rate limited", {}, mock.Mock(read=lambda: b"{}"))

    @staticmethod
    def _fake_response(payload):
        response = mock.MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response


if __name__ == "__main__":
    unittest.main()
