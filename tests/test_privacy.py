import unittest

from src.privacy import is_excluded, redact_text


class PrivacyTests(unittest.TestCase):
    def test_redacts_configured_patterns_without_returning_secret_values(self):
        result = redact_text(
            "api_key=abc123 and password: hunter2",
            [r"(?i)api[_ -]?key\s*[:=]\s*[^\s]+", r"(?i)password\s*[:=]\s*[^\s]+"],
        )

        self.assertEqual(result.text, "[REDACTED] and [REDACTED]")
        self.assertEqual(result.rules, ["pattern-1", "pattern-2"])
        self.assertNotIn("abc123", result.text)
        self.assertNotIn("hunter2", result.text)

    def test_redacts_private_key_blocks(self):
        result = redact_text(
            "before -----BEGIN PRIVATE KEY-----secret-----END PRIVATE KEY----- after",
            [r"(?is)-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----"],
        )

        self.assertEqual(result.text, "before [REDACTED] after")

    def test_excludes_application_or_window_title_case_insensitively(self):
        config = {
            "excludedApplications": ["MessagingApp"],
            "excludedWindowTitlePatterns": [r"^Private - ", r"\bsecret\b"],
        }

        self.assertTrue(is_excluded("messagingapp", "normal chat", config))
        self.assertTrue(is_excluded("chrome", "Private - browsing", config))
        self.assertTrue(is_excluded("chrome", "A SECRET document", config))
        self.assertFalse(is_excluded("chrome", "Public documentation", config))


if __name__ == "__main__":
    unittest.main()
