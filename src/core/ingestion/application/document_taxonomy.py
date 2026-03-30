"""
Document Taxonomy Classifier
=============================

Maps folder names and document titles to structured taxonomy fields:
  - product_line: always "acme-mail" for known folders
  - edition:      commercial | ce | unknown
  - audience:     admin | user | mixed | unknown
  - source_family: admin_guide | ce_guide | user_guide | zendesk_kb | unknown

Usage::

    from src.core.ingestion.application.document_taxonomy import classify_document_taxonomy

    taxonomy = classify_document_taxonomy(
        folder_name="AdminGuide",
        document_title="How to configure domains",
    )
    # {"product_line": "acme-mail", "edition": "commercial",
    #  "audience": "admin", "source_family": "admin_guide"}
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Keyword lists for ZendeskKB audience heuristic
# ---------------------------------------------------------------------------

_USER_KEYWORDS: frozenset[str] = frozenset(
    [
        "webmail",
        "chat",
        "message search",
        "send later",
        "contacts",
        "calendar",
        "appointments",
        "files",
        "send email",
        "junk mail",
        "inbox",
    ]
)

_ADMIN_KEYWORDS: frozenset[str] = frozenset(
    [
        "install",
        "upgrade",
        "ansible",
        "domain",
        "credentials",
        "cbpolicyd",
        "backup",
        "cli",
        "admin panel",
        "server",
        "provision",
        "policy",
        "directory",
        "smtp",
        "ldap",
    ]
)

# ---------------------------------------------------------------------------
# Folder → taxonomy table
# ---------------------------------------------------------------------------

_FOLDER_TAXONOMY: dict[str, dict[str, str]] = {
    "adminguide": {
        "product_line": "acme-mail",
        "edition": "commercial",
        "audience": "admin",
        "source_family": "admin_guide",
    },
    "ceguide": {
        "product_line": "acme-mail",
        "edition": "ce",
        "audience": "admin",
        "source_family": "ce_guide",
    },
    "userguide": {
        "product_line": "acme-mail",
        "edition": "commercial",
        "audience": "user",
        "source_family": "user_guide",
    },
}

_UNKNOWN_TAXONOMY: dict[str, str] = {
    "product_line": "acme-mail",
    "edition": "unknown",
    "audience": "unknown",
    "source_family": "unknown",
}


def _classify_zendesk_audience(document_title: str | None) -> str:
    """Return 'admin', 'user', or 'unknown' based on title keywords.

    Admin wins when both signal types are present (conservative default).
    """
    if not document_title:
        return "unknown"

    lower = document_title.lower()

    has_admin = any(kw in lower for kw in _ADMIN_KEYWORDS)
    has_user = any(kw in lower for kw in _USER_KEYWORDS)

    if has_admin:
        return "admin"
    if has_user:
        return "user"
    return "unknown"


def classify_document_taxonomy(
    folder_name: str | None,
    document_title: str | None = None,
) -> dict[str, str]:
    """Return taxonomy dict for a document given its folder name and optional title.

    Args:
        folder_name:    The folder's display name (e.g. "AdminGuide").
                        Case-insensitive. None or unrecognised folders yield ``unknown``.
        document_title: Used only for ZendeskKB audience heuristics.

    Returns:
        Dict with keys: product_line, edition, audience, source_family.
    """
    if not folder_name:
        return dict(_UNKNOWN_TAXONOMY)

    key = folder_name.lower().strip()

    # Exact folder match
    if key in _FOLDER_TAXONOMY:
        return dict(_FOLDER_TAXONOMY[key])

    # ZendeskKB: edition is commercial, audience inferred from title
    if key == "zendesk_kb" or key == "zendeskkb":
        return {
            "product_line": "acme-mail",
            "edition": "commercial",
            "audience": _classify_zendesk_audience(document_title),
            "source_family": "zendesk_kb",
        }

    return dict(_UNKNOWN_TAXONOMY)
