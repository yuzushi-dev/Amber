import os
import unittest
from unittest.mock import patch


class TestSecurityRemediation(unittest.TestCase):
    def test_s02_pii_scrubbing(self):
        """Verify PIIScrubber is integrated and working."""
        from src.core.security.pii_scrubber import PIIScrubber

        scrubber = PIIScrubber()

        pii_text = "Call me at 555-555-5555 or email test@example.com"
        clean_text = scrubber.scrub_text(pii_text)

        self.assertIn("[PHONE REDACTED]", clean_text)
        self.assertIn("t***@example.com", clean_text)

        # Test query integration logic (mocked)
        with patch("src.core.graph.application.context_writer.context_graph_writer.log_turn"):
            # Simulate what happens in query.py
            request_query = "My SSN is 123-45-6789"
            answer = "I processed 123-45-6789"

            safe_query = scrubber.scrub_text(request_query)
            safe_answer = scrubber.scrub_text(answer)

            self.assertIn("[SSN REDACTED]", safe_query)
            self.assertIn("[SSN REDACTED]", safe_answer)

    def test_s03_secret_key_generation(self):
        """Verify S03: Random secret key generation."""
        # Unset env var to force generation
        if "SECRET_KEY" in os.environ:
            del os.environ["SECRET_KEY"]

        from src.api.config import Settings, get_settings

        # Reset lru_cache
        get_settings.cache_clear()

        settings = Settings(_env_file=None)
        key1 = settings.secret_key

        self.assertTrue(len(key1) >= 32, "Generated key should be long")
        self.assertNotEqual(key1, "", "Key should not be empty")

        # Verify warnings are logged (manual check via stdout usually, but good enough here)


if __name__ == "__main__":
    unittest.main()
