import tempfile
import unittest
from pathlib import Path

from src.privacy_state import is_private_mode, set_private_mode


class PrivacyStateTests(unittest.TestCase):
    def test_defaults_to_disabled_when_no_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(is_private_mode(Path(directory)))

    def test_round_trips_enabled_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_private_mode(root, True, reason="hotkey")
            self.assertTrue(is_private_mode(root))
            set_private_mode(root, False)
            self.assertFalse(is_private_mode(root))

    def test_malformed_state_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "private-mode.json").write_text("not json", encoding="utf-8")
            self.assertTrue(is_private_mode(root))


if __name__ == "__main__":
    unittest.main()
