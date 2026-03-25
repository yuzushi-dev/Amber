"""
Security Utilities
==================

API key hashing, generation, and verification utilities.
"""

import hashlib
import hmac
import secrets
from base64 import b64encode

# from src.api.config import settings # DELETED: direct import violation

_SECRET_KEY: str = "default-insecure-key"
_SECRET_KEY_OLD: str | None = None


def configure_security(secret_key: str, secondary_key: str | None = None) -> None:
    """
    Configure security module with application secret(s).

    Args:
        secret_key: Primary secret used for new hashes.
        secondary_key: Previous secret still accepted during rotation window.
                       When provided, verify_api_key() will try both keys.
    """
    global _SECRET_KEY, _SECRET_KEY_OLD
    _SECRET_KEY = secret_key
    _SECRET_KEY_OLD = secondary_key


def _get_salt() -> bytes:
    """Get the primary salt for hashing."""
    return _SECRET_KEY.encode("utf-8")


def hash_api_key(key: str) -> str:
    """
    Hash an API key using SHA-256 with the secret key as salt.

    Args:
        key: Raw API key to hash

    Returns:
        str: Hashed API key (hex encoded)
    """
    salt = _get_salt()
    # Use HMAC-SHA256 for secure hashing
    hashed = hmac.new(salt, key.encode("utf-8"), hashlib.sha256)
    return hashed.hexdigest()


def verify_api_key(key: str, hashed: str) -> bool:
    """
    Verify an API key against its hash using constant-time comparison.

    Tries the primary key first.  If a secondary key is registered (rotation
    window), also tries that so existing hashes remain valid during rotation.

    Args:
        key: Raw API key to verify
        hashed: Previously hashed API key

    Returns:
        bool: True if the key matches the hash with either active secret
    """
    # Try primary key
    computed_primary = hash_api_key(key)
    if hmac.compare_digest(computed_primary, hashed):
        return True

    # Try secondary key (rotation window) — constant-time even on branch
    if _SECRET_KEY_OLD is not None:
        salt_old = _SECRET_KEY_OLD.encode("utf-8")
        computed_old = hmac.new(salt_old, key.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed_old, hashed)

    return False


def generate_api_key(prefix: str = "grap") -> str:
    """
    Generate a cryptographically secure API key.

    Format: {prefix}_{32 random bytes base64 encoded}
    Example: grap_Abc123XyzDef456...

    Args:
        prefix: Key prefix for identification (default: "grap" for GraphRAG)

    Returns:
        str: Generated API key
    """
    # Generate 32 random bytes (256 bits of entropy)
    random_bytes = secrets.token_bytes(32)
    # Encode as URL-safe base64 and remove padding
    encoded = b64encode(random_bytes).decode("utf-8").rstrip("=")
    # Replace URL-unsafe characters
    encoded = encoded.replace("+", "-").replace("/", "_")
    return f"{prefix}_{encoded}"


def mask_api_key(key: str) -> str:
    """
    Mask an API key for safe logging.

    Shows only the prefix and last 4 characters.
    Example: grap_****...****abcd

    Args:
        key: API key to mask

    Returns:
        str: Masked API key
    """
    if not key or len(key) < 10:
        return "****"

    if "_" in key:
        prefix, rest = key.split("_", 1)
        return f"{prefix}_****...****{rest[-4:]}"

    return f"****...****{key[-4:]}"
