"""
Security Utilities
==================

API key hashing, generation, and verification utilities.
"""

import hashlib
import hmac
import secrets
from base64 import b64encode
from typing import Any

from src.api.config import settings


def _get_salt() -> bytes:
    """Get the salt for hashing from the secret key."""
    return settings.secret_key.encode("utf-8")


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

    Args:
        key: Raw API key to verify
        hashed: Previously hashed API key

    Returns:
        bool: True if the key matches the hash
    """
    computed_hash = hash_api_key(key)
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(computed_hash, hashed)


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


# =============================================================================
# In-Memory API Key Store (for Phase 0)
# Will be replaced with database storage in later phases
# =============================================================================

# Sample API keys for development/testing
# In production, these should come from a database
_DEFAULT_API_KEY = generate_api_key()
_DEFAULT_API_KEY_HASH = hash_api_key(_DEFAULT_API_KEY)

# Support fixed dev API key from environment
import os
_DEV_API_KEY = os.getenv("DEV_API_KEY", "amber-dev-key-2024")
_DEV_API_KEY_HASH = hash_api_key(_DEV_API_KEY)

# API key storage: hash -> metadata
API_KEYS: dict[str, dict[str, Any]] = {
    _DEFAULT_API_KEY_HASH: {
        "tenant_id": "default",
        "name": "Default Development Key",
        "permissions": ["read", "write", "admin"],
        "active": True,
    },
    _DEV_API_KEY_HASH: {
        "tenant_id": "default",
        "name": "Fixed Dev Key",
        "permissions": ["read", "write", "admin"],
        "active": True,
    },
}


def lookup_api_key(key: str) -> dict[str, Any] | None:
    """
    Look up an API key and return its metadata.

    Args:
        key: Raw API key to look up

    Returns:
        dict or None: Key metadata if found and valid, None otherwise
    """
    key_hash = hash_api_key(key)

    metadata = API_KEYS.get(key_hash)
    if metadata and metadata.get("active", True):
        return metadata

    return None


def register_api_key(key: str, tenant_id: str, name: str, permissions: list[str]) -> str:
    """
    Register a new API key.

    Args:
        key: Raw API key to register
        tenant_id: Tenant this key belongs to
        name: Human-readable name for the key
        permissions: List of permissions for this key

    Returns:
        str: The hashed key
    """
    key_hash = hash_api_key(key)
    API_KEYS[key_hash] = {
        "tenant_id": tenant_id,
        "name": name,
        "permissions": permissions,
        "active": True,
    }
    return key_hash


# Print the default key on module load (for development)
if settings.debug:
    import logging

    logging.getLogger(__name__).info(f"Default API key: {_DEFAULT_API_KEY}")
