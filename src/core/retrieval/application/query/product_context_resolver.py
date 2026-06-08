"""
Product Context Resolver
========================

Infers query-time taxonomy context (edition, audience) from the user's question
using deterministic keyword rules — no LLM required for v1.

Resolution order:
1. Explicit CE mention  -> edition=ce
2. Admin-specific terms -> audience=admin, edition=commercial (default)
3. User-task terms      -> audience=user, edition=commercial (default)
4. Ambiguous            -> edition=commercial, audience=admin (conservative default)

Confidence levels:
  1.0 - explicit CE or admin/user term
  0.7 - inferred from general admin/user vocabulary
  0.4 - default fallback
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_CE_TERMS: frozenset[str] = frozenset(
    ["community edition", " ce ", " ce.", " ce,", " ce?", "(ce)"]
)

_USER_TERMS: frozenset[str] = frozenset(
    [
        "webmail",
        "message search",
        "send email",
        "send an email",
        "send later",
        "contacts",
        "calendar",
        "appointments",
        "chat",
        "junk mail",
        "inbox",
        "my email",
        "my calendar",
        "my files",
    ]
)

_ADMIN_TERMS: frozenset[str] = frozenset(
    [
        "delegate admin",
        "domain",
        "install",
        "upgrade",
        "ansible",
        "credentials",
        "cbpolicyd",
        "backup",
        " cli ",
        "admin panel",
        "server",
        "provision",
        "policy",
        "directory server",
        "smtp",
        "ldap",
        "deployment",
        "configure",
        "setup",
    ]
)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ProductContext:
    """Resolved product context for a query."""

    edition: str = "commercial"       # commercial | ce | unknown
    audience: str = "admin"           # admin | user | unknown
    product_line: str = "acme_mail"
    confidence: float = 0.4
    reason: str = "default"


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def resolve_product_context(query: str) -> ProductContext:
    """Infer product context from a query string.

    Returns a ProductContext with edition, audience, confidence, and reason.
    Never raises — ambiguous input produces a low-confidence commercial/admin default.
    """
    if not query:
        return ProductContext(
            edition="commercial",
            audience="admin",
            confidence=0.2,
            reason="empty_query",
        )

    lower = " " + query.lower() + " "

    # 1. Detect CE explicitly
    is_ce = any(term in lower for term in _CE_TERMS)

    # 2. Detect audience signal
    has_user = any(term in lower for term in _USER_TERMS)
    has_admin = any(term in lower for term in _ADMIN_TERMS)

    edition = "ce" if is_ce else "commercial"

    if has_user and not has_admin:
        return ProductContext(
            edition=edition,
            audience="user",
            confidence=1.0,
            reason="user_term_match",
        )

    if has_admin:
        return ProductContext(
            edition=edition,
            audience="admin",
            confidence=1.0,
            reason="admin_term_match",
        )

    if is_ce:
        # CE mentioned but no audience signal — default to admin
        return ProductContext(
            edition="ce",
            audience="admin",
            confidence=0.7,
            reason="ce_explicit_admin_default",
        )

    # 3. Conservative default: commercial/admin
    return ProductContext(
        edition="commercial",
        audience="admin",
        confidence=0.4,
        reason="default_fallback",
    )
