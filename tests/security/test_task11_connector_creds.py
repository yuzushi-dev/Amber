"""
Security tests for Task 11: connector credential encryption.

Verifies that:
- encrypt_credentials / decrypt_credentials round-trips correctly
- Credentials are stored as ciphertext (not plaintext JSON) in encrypted_credentials
- connectors.py authenticate writes to encrypted_credentials (not raw sync_cursor)
- connectors.py browse/sync reads from encrypted_credentials
- sync_cursor no longer holds raw credential fields
"""

import inspect
import json
import pytest


# ── encryption helpers ────────────────────────────────────────────────────────


def test_encrypt_credentials_roundtrip():
    """encrypt then decrypt must return the original dict."""
    from src.shared.security import encrypt_credentials, decrypt_credentials, configure_security

    configure_security("test-secret-key-for-tests")
    data = {"api_token": "my-token", "subdomain": "acme", "email": "a@b.com"}
    token = encrypt_credentials(data)

    assert isinstance(token, str)
    assert "api_token" not in token  # must not be plaintext

    recovered = decrypt_credentials(token)
    assert recovered == data


def test_encrypt_credentials_ciphertext_is_opaque():
    """The encrypted blob must not contain raw credential values."""
    from src.shared.security import encrypt_credentials, configure_security

    configure_security("test-secret-key-for-tests")
    data = {"api_token": "super-secret-12345", "password": "hunter2"}
    token = encrypt_credentials(data)

    assert "super-secret-12345" not in token
    assert "hunter2" not in token


def test_decrypt_credentials_returns_none_on_garbage():
    """decrypt_credentials must return None (not raise) on invalid ciphertext."""
    from src.shared.security import decrypt_credentials, configure_security

    configure_security("test-secret-key-for-tests")
    result = decrypt_credentials("this-is-not-valid-fernet")
    assert result is None


def test_decrypt_credentials_returns_none_wrong_key():
    """Credentials encrypted with one key must not decrypt with a different key."""
    from src.shared.security import encrypt_credentials, decrypt_credentials, configure_security

    configure_security("key-one")
    token = encrypt_credentials({"api_token": "secret"})

    configure_security("key-two")
    result = decrypt_credentials(token)
    assert result is None, "Wrong key must not decrypt ciphertext"


# ── connector model ───────────────────────────────────────────────────────────


def test_connector_state_model_has_encrypted_credentials_column():
    """ConnectorState ORM model must have an encrypted_credentials mapped column."""
    from src.core.ingestion.domain.connector_state import ConnectorState
    import sqlalchemy as sa

    columns = {c.name: c for c in ConnectorState.__table__.columns}
    assert "encrypted_credentials" in columns, (
        "ConnectorState is missing 'encrypted_credentials' column. "
        "Raw credentials are stored in plaintext sync_cursor JSONB."
    )
    col = columns["encrypted_credentials"]
    assert col.nullable is True, "encrypted_credentials should be nullable (migration path)"


# ── connectors.py route source checks ────────────────────────────────────────


def _connectors_source() -> str:
    import src.api.routes.connectors as m
    return inspect.getsource(m)


def test_authenticate_stores_encrypted_credentials():
    """
    authenticate_connector must call encrypt_credentials and write to
    state.encrypted_credentials, not state.sync_cursor with raw credentials.
    """
    source = _connectors_source()
    assert "encrypt_credentials" in source, (
        "connectors.py authenticate does not call encrypt_credentials(). "
        "Raw credentials are written to sync_cursor."
    )


def test_browse_reads_encrypted_credentials():
    """browse_connector must decrypt from encrypted_credentials."""
    source = _connectors_source()
    assert "decrypt_credentials" in source, (
        "connectors.py browse does not call decrypt_credentials(). "
        "It is still reading raw credentials from sync_cursor."
    )


def test_sync_cursor_no_raw_credential_fields():
    """
    After the fix, sync_cursor should no longer store raw credential keys.
    Specifically, 'sync_cursor = request.credentials' must be gone.
    """
    source = _connectors_source()
    assert "sync_cursor = request.credentials" not in source, (
        "connectors.py still assigns raw credentials to sync_cursor. "
        "Credentials must go through encrypt_credentials first."
    )
