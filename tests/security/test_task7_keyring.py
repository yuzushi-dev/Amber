"""
Security tests for Task 7: dual-secret keyring for SECRET_KEY rotation.

Verifies that:
- verify_api_key() accepts hashes made with the primary key
- verify_api_key() also accepts hashes made with the secondary key (rotation window)
- hash_api_key() always uses the primary key for new hashes
- Settings exposes SECRET_KEY_OLD for the secondary key
"""



# ── Keyring: verify accepts primary-key hashes ───────────────────────────────


def test_verify_api_key_accepts_primary_hash():
    """A key hashed with the current primary secret must verify correctly."""
    from src.shared.security import configure_security, hash_api_key, verify_api_key

    configure_security("primary-secret-new", secondary_key=None)
    raw = "test-api-key-abc"
    h = hash_api_key(raw)
    assert verify_api_key(raw, h), "Primary-key hash must verify against current primary"


def test_verify_api_key_accepts_secondary_hash():
    """
    A hash made with the OLD key must still verify when that key is registered
    as the secondary (rotation window).  Without this, key rotation requires
    instant DB rehash or a service interruption.
    """
    from src.shared.security import configure_security, hash_api_key, verify_api_key

    # Phase 1: hash was made when old-secret was primary
    configure_security("old-secret")
    raw = "test-api-key-abc"
    old_hash = hash_api_key(raw)

    # Phase 2: new secret promoted to primary, old kept as secondary
    configure_security("new-secret", secondary_key="old-secret")

    assert verify_api_key(raw, old_hash), (
        "verify_api_key() rejected a hash made under the old secret. "
        "SECRET_KEY rotation requires a service interruption or instant DB rehash."
    )


def test_hash_api_key_uses_primary_not_secondary():
    """
    hash_api_key() must produce a hash using the primary key, not the secondary.
    New API keys must be hashed with the current primary.
    """
    from src.shared.security import configure_security, hash_api_key, verify_api_key

    configure_security("primary-key", secondary_key="old-key")
    raw = "fresh-api-key-xyz"
    new_hash = hash_api_key(raw)

    # Verify against primary (should pass)
    configure_security("primary-key", secondary_key=None)
    assert verify_api_key(raw, new_hash), "New hash must verify with primary key"

    # Verify against secondary as primary (should fail — was not hashed with old-key)
    configure_security("old-key", secondary_key=None)
    assert not verify_api_key(raw, new_hash), (
        "New hash should NOT verify with the old key — hash_api_key() must use the primary"
    )


def test_verify_api_key_rejects_wrong_key():
    """
    A completely wrong key must not verify — even with secondary key configured.
    """
    from src.shared.security import configure_security, hash_api_key, verify_api_key

    configure_security("primary", secondary_key="secondary")
    h = hash_api_key("correct-key")

    assert not verify_api_key("wrong-key", h), "Wrong key must not verify"


# ── Settings: SECRET_KEY_OLD field ────────────────────────────────────────────


def test_settings_exposes_secret_key_old():
    """
    Settings must expose a secret_key_old field (env: SECRET_KEY_OLD) so
    operators can register the previous secret during rotation without code changes.
    """
    from src.api.config import Settings
    fields = Settings.model_fields
    assert "secret_key_old" in fields, (
        "Settings missing 'secret_key_old' field. "
        "Operators cannot perform zero-downtime SECRET_KEY rotation."
    )


def test_configure_security_accepts_secondary_key_param():
    """configure_security() must accept a secondary_key keyword argument."""
    import inspect

    from src.shared import security as sec_module
    sig = inspect.signature(sec_module.configure_security)
    assert "secondary_key" in sig.parameters, (
        "configure_security() has no secondary_key parameter. "
        "Zero-downtime rotation is not possible."
    )
