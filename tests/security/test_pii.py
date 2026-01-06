from src.core.security.pii_scrubber import PIIScrubber
from src.core.security.source_verifier import SourceVerifier


class TestPIIScrubber:
    def test_scrub_email(self):
        scrubber = PIIScrubber()
        text = "Contact me at john.doe@example.com"
        scrubbed = scrubber.scrub_text(text)
        assert "john.doe@example.com" not in scrubbed
        assert "j***@example.com" in scrubbed

        text = "me@yo.com"
        scrubbed = scrubber.scrub_text(text)
        assert "***@yo.com" in scrubbed

    def test_scrub_phone(self):
        scrubber = PIIScrubber()
        # Test various formats
        assert "[PHONE REDACTED]" in scrubber.scrub_text("Call 555-456-7890")
        assert "[PHONE REDACTED]" in scrubber.scrub_text("(555) 456-7890")
        assert "[PHONE REDACTED]" in scrubber.scrub_text("555.456.7890")

    def test_scrub_ssn(self):
        scrubber = PIIScrubber()
        text = "My SSN is 123-45-6789"
        scrubbed = scrubber.scrub_text(text)
        assert "[SSN REDACTED]" in scrubbed
        assert "123-45-6789" not in scrubbed

    def test_scrub_credit_card(self):
        scrubber = PIIScrubber()
        # 16 digits
        text = "Card: 1234-5678-1234-5678"
        scrubbed = scrubber.scrub_text(text)
        assert "[CREDIT CARD REDACTED]" in scrubbed

class TestSourceVerifier:
    def test_verify_citation_exact(self):
        verifier = SourceVerifier()
        source = "The quick brown fox jumps over the lazy dog."
        citation = "brown fox jumps"
        assert verifier.verify_citation(citation, source)

    def test_verify_citation_normalized(self):
        verifier = SourceVerifier()
        source = "The quick brown fox jumps over the lazy dog."
        citation = "BROWN  FOX   JUMPS"
        assert verifier.verify_citation(citation, source)

    def test_verify_citation_fail(self):
        verifier = SourceVerifier()
        source = "The quick brown fox jumps over the lazy dog."
        citation = "white rabbit runs"
        assert not verifier.verify_citation(citation, source)
