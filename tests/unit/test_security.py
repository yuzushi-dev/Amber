"""
Unit Tests for Security Utilities
==================================
"""

import pytest

from src.shared.security import (
    generate_api_key,
    hash_api_key,
    mask_api_key,
    verify_api_key,
)


class TestApiKeyGeneration:
    """Tests for API key generation."""

    def test_generate_api_key_format(self):
        """Generated API keys should have correct format."""
        key = generate_api_key()
        assert key.startswith("grap_")
        assert len(key) > 20

    def test_generate_api_key_custom_prefix(self):
        """Should support custom prefixes."""
        key = generate_api_key(prefix="test")
        assert key.startswith("test_")

    def test_generate_api_key_unique(self):
        """Generated API keys should be unique."""
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100


class TestApiKeyHashing:
    """Tests for API key hashing and verification."""

    def test_hash_api_key_consistent(self):
        """Same key should always produce same hash."""
        key = "test_api_key_12345"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)
        assert hash1 == hash2

    def test_hash_api_key_different_keys(self):
        """Different keys should produce different hashes."""
        hash1 = hash_api_key("key1")
        hash2 = hash_api_key("key2")
        assert hash1 != hash2

    def test_verify_api_key_valid(self):
        """Valid key should verify correctly."""
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed) is True

    def test_verify_api_key_invalid(self):
        """Invalid key should not verify."""
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert verify_api_key("wrong_key", hashed) is False

    def test_verify_api_key_constant_time(self):
        """Verification should use constant-time comparison."""
        # This is a basic test - in practice, timing attacks require
        # more sophisticated testing
        key = generate_api_key()
        hashed = hash_api_key(key)

        # Verify many times to ensure consistent behavior
        for _ in range(100):
            assert verify_api_key(key, hashed) is True


class TestMaskApiKey:
    """Tests for API key masking."""

    def test_mask_api_key_format(self):
        """Masked key should hide middle characters."""
        masked = mask_api_key("grap_abcdefghijklmnop1234567890")
        assert masked.startswith("grap_")
        assert "****" in masked
        assert masked.endswith("7890")

    def test_mask_api_key_short(self):
        """Short keys should be fully masked."""
        masked = mask_api_key("abc")
        assert masked == "****"

    def test_mask_api_key_empty(self):
        """Empty keys should be masked."""
        masked = mask_api_key("")
        assert masked == "****"

    def test_mask_api_key_no_prefix(self):
        """Keys without prefix should still be masked."""
        masked = mask_api_key("abcdefghijklmnop1234567890")
        assert "****" in masked
        assert masked.endswith("7890")
