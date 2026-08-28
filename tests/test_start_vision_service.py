import unittest

from src.start_vision_service import find_model_key

SAMPLE = (
    '[{"type":"llm","modelKey":"qwen/qwen3-vl-8b","format":"gguf","displayName":"Qwen3 VL 8B",'
    '"publisher":"qwen","path":"qwen/qwen3-vl-8b","vision":true},'
    '{"type":"embedding","modelKey":"text-embedding-nomic-embed-text-v1.5","format":"gguf",'
    '"displayName":"Nomic Embed Text v1.5","publisher":"nomic-ai"}]'
)


class FindModelKeyTests(unittest.TestCase):
    def test_finds_model_key_by_pattern(self):
        self.assertEqual(find_model_key(SAMPLE, "qwen3-vl"), "qwen/qwen3-vl-8b")

    def test_returns_none_when_pattern_not_found(self):
        self.assertIsNone(find_model_key(SAMPLE, "does-not-exist"))

    def test_returns_none_on_invalid_json(self):
        self.assertIsNone(find_model_key("not json", "qwen"))

    def test_returns_none_on_empty_list(self):
        self.assertIsNone(find_model_key("[]", "qwen"))


if __name__ == "__main__":
    unittest.main()
