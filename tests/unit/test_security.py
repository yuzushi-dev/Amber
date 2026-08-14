"""
Unit Tests for Security Utilities
==================================
"""

import re
from pathlib import Path

from src.shared.security import (
    configure_security,
    decrypt_credentials,
    encrypt_credentials,
    generate_api_key,
    hash_api_key,
    mask_api_key,
    verify_api_key,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Matches a manifest line/entry that *declares* cryptography as a dependency,
# e.g. "cryptography==50.0.0" (requirements*.txt) or '"cryptography>=44.0.0"'
# (pyproject.toml). Stricter than a bare substring check so a comment
# mentioning the word "cryptography" can't satisfy it.
_CRYPTOGRAPHY_DECLARATION = re.compile(r"^[\s\"']*cryptography\s*[=<>~!]", re.IGNORECASE | re.MULTILINE)


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


class TestCredentialEncryption:
    """
    Tests for encrypt_credentials/decrypt_credentials (connector credentials
    at rest, src/shared/security.py). These do a REAL Fernet roundtrip via the
    `cryptography` package -- not a mock -- so they fail with a
    ModuleNotFoundError if `cryptography` is missing from the environment,
    same as it was in production.

    This class lives in tests/unit (not tests/security) deliberately:
    scripts/verify.sh, which backs the CI quality-gate, only runs
    `pytest -q tests/unit`. An equivalent, more detailed test already existed
    in tests/security/test_task11_connector_creds.py, but tests/security is
    never executed by CI, so it never had a chance to catch the missing
    `cryptography` dependency. See PR description for the residual-risk note
    on this CI/tests-directory gap.
    """

    def test_encrypt_decrypt_credentials_roundtrip(self):
        configure_security("test-secret-key-for-tests")
        data = {"api_token": "my-token", "subdomain": "acme", "email": "a@b.com"}
        token = encrypt_credentials(data)

        assert isinstance(token, str)
        assert "api_token" not in token  # must not be plaintext

        recovered = decrypt_credentials(token)
        assert recovered == data

    def test_decrypt_credentials_returns_none_on_garbage(self):
        configure_security("test-secret-key-for-tests")
        assert decrypt_credentials("this-is-not-valid-fernet") is None

    def test_cryptography_declared_in_docker_build_manifest(self):
        """
        `cryptography` is imported directly by encrypt_credentials/
        decrypt_credentials but was, until this fix, declared nowhere as a
        direct dependency -- it only appeared in uv.lock, pinned there
        because uv's resolver locked an older unstructured-client (0.42.8)
        that happens to require cryptography. uv.lock is never consulted at
        build time: docker/api.Dockerfile and docker/worker.Dockerfile both
        run `pip install -r requirements-core.txt`, and plain pip's resolver
        picks a newer unstructured-client (0.46.1) that has dropped the
        cryptography dependency entirely -- confirmed both via wheel METADATA
        and via a clean `pip install --dry-run -r requirements-core.txt`
        against the pre-fix manifest (zero occurrences of "cryptography" in
        the resolved install set).
        """
        core_requirements = (PROJECT_ROOT / "requirements-core.txt").read_text()
        assert _CRYPTOGRAPHY_DECLARATION.search(core_requirements), (
            "cryptography is imported directly by src/shared/security.py "
            "(encrypt_credentials/decrypt_credentials) but is not declared in "
            "requirements-core.txt, which is what docker/api.Dockerfile and "
            "docker/worker.Dockerfile actually install at build time."
        )

    def test_cryptography_declared_in_pyproject(self):
        """`cryptography` must also be a direct pyproject.toml dependency (used by CI)."""
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
        assert _CRYPTOGRAPHY_DECLARATION.search(pyproject)


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
