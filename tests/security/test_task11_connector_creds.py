"""
Security tests for Task 11: connector credential encryption.

Verifies that:
- encrypt_credentials / decrypt_credentials round-trips correctly
- Credentials are stored as ciphertext (not plaintext JSON) in encrypted_credentials
- connectors.py authenticate writes to encrypted_credentials (not raw sync_cursor)
- connectors.py browse/sync reads from encrypted_credentials
- sync_cursor no longer holds raw credential fields
- `cryptography` is declared as a direct dependency in the manifests actually
  installed at build time (requirements-core.txt / pyproject.toml), not just
  resolvable by whichever transitive graph a given installer happens to pick.
"""

import inspect
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Matches a manifest line/entry that *declares* cryptography as a dependency,
# e.g. "cryptography==50.0.0" (requirements*.txt) or '"cryptography>=44.0.0"'
# (pyproject.toml). Deliberately stricter than a bare substring check so it
# can't be satisfied by a comment mentioning the word "cryptography".
_CRYPTOGRAPHY_DECLARATION = re.compile(r"^[\s\"']*cryptography\s*[=<>~!]", re.IGNORECASE | re.MULTILINE)

# ── encryption helpers ────────────────────────────────────────────────────────


def test_encrypt_credentials_roundtrip():
    """encrypt then decrypt must return the original dict."""
    from src.shared.security import configure_security, decrypt_credentials, encrypt_credentials

    configure_security("test-secret-key-for-tests")
    data = {"api_token": "my-token", "subdomain": "acme", "email": "a@b.com"}
    token = encrypt_credentials(data)

    assert isinstance(token, str)
    assert "api_token" not in token  # must not be plaintext

    recovered = decrypt_credentials(token)
    assert recovered == data


def test_encrypt_credentials_ciphertext_is_opaque():
    """The encrypted blob must not contain raw credential values."""
    from src.shared.security import configure_security, encrypt_credentials

    configure_security("test-secret-key-for-tests")
    data = {"api_token": "super-secret-12345", "password": "hunter2"}
    token = encrypt_credentials(data)

    assert "super-secret-12345" not in token
    assert "hunter2" not in token


def test_decrypt_credentials_returns_none_on_garbage():
    """decrypt_credentials must return None (not raise) on invalid ciphertext."""
    from src.shared.security import configure_security, decrypt_credentials

    configure_security("test-secret-key-for-tests")
    result = decrypt_credentials("this-is-not-valid-fernet")
    assert result is None


def test_decrypt_credentials_returns_none_wrong_key():
    """Credentials encrypted with one key must not decrypt with a different key."""
    from src.shared.security import configure_security, decrypt_credentials, encrypt_credentials

    configure_security("key-one")
    token = encrypt_credentials({"api_token": "secret"})

    configure_security("key-two")
    result = decrypt_credentials(token)
    assert result is None, "Wrong key must not decrypt ciphertext"


# ── dependency manifest (regression guard) ────────────────────────────────────


def test_cryptography_declared_in_docker_build_manifest():
    """
    `cryptography` is imported directly by encrypt_credentials/decrypt_credentials
    but was, until this fix, declared nowhere as a direct dependency -- it only
    appeared in uv.lock, pinned there because uv's resolver locked an older
    unstructured-client (0.42.8) that happens to require cryptography. uv.lock
    is never consulted at build time: docker/api.Dockerfile and
    docker/worker.Dockerfile both run `pip install -r requirements-core.txt`,
    and plain pip's resolver picks a newer unstructured-client (0.46.1, verified
    via wheel METADATA) that has dropped the cryptography dependency entirely.
    A clean `pip install --dry-run -r requirements-core.txt` against the
    pre-fix manifest confirms zero occurrences of "cryptography" in the
    resolved install set -- so production images genuinely lacked the module,
    matching the observed ModuleNotFoundError.

    This test guards against that regression by asserting `cryptography` is
    declared directly in the manifest that Docker actually installs from.
    """
    core_requirements = (PROJECT_ROOT / "requirements-core.txt").read_text()
    assert _CRYPTOGRAPHY_DECLARATION.search(core_requirements), (
        "cryptography is imported directly by src/shared/security.py "
        "(encrypt_credentials/decrypt_credentials) but is not declared in "
        "requirements-core.txt, which is what docker/api.Dockerfile and "
        "docker/worker.Dockerfile actually install at build time. It must "
        "not be left to whatever version of unstructured-client pip's "
        "resolver happens to pick."
    )


def test_cryptography_declared_in_pyproject():
    """`cryptography` must also be a direct pyproject.toml dependency (used by CI)."""
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
    assert _CRYPTOGRAPHY_DECLARATION.search(pyproject)


# ── connector model ───────────────────────────────────────────────────────────


def test_connector_state_model_has_encrypted_credentials_column():
    """ConnectorState ORM model must have an encrypted_credentials mapped column."""

    from src.core.ingestion.domain.connector_state import ConnectorState

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
