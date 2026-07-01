"""
Product Context Resolver
========================

Infers query-time taxonomy context (edition, audience) from the user's question
using deterministic keyword rules — no LLM required for v1.

Resolution order:
1. Dual mention (CE + commercial contrast) -> editions=[commercial, ce]
2. Explicit CE mention  -> edition=ce
3. Admin-specific terms -> audience=admin, edition=commercial (default)
4. User-task terms      -> audience=user, edition=commercial (default)
5. Ambiguous            -> edition=commercial, audience=admin (conservative default)

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

# Contrastive markers indicating the query is comparing/relating the two editions
# (e.g. "similar feature ... in CE", "difference between", "both editions").
# These are only consulted when a CE marker is ALSO present — they turn a
# single-edition (ce-only) resolution into a dual-edition one so downstream
# filtering matches BOTH commercial and ce docs instead of excluding commercial.
_DUAL_MENTION_TERMS: frozenset[str] = frozenset(
    [
        "similar",
        "difference",
        "different",
        "compare",
        "compared",
        "comparison",
        " vs ",
        "versus",
        "both",
        "as well",
        "also",
        "either",
        "equivalent",
        "counterpart",
    ]
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
    # When the query references BOTH editions (e.g. "how does X work? is there a
    # similar feature in CE?"), this holds the full set to match. `edition` stays
    # the single primary/first value for backward compat with scalar callers;
    # downstream taxonomy filtering should prefer `editions` when present.
    editions: list[str] | None = None


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

    # 1b. Dual-edition mention: CE is referenced AND the query is contrasting it
    # with the (non-CE) commercial edition. In that case we must match BOTH
    # editions downstream, not just ce — otherwise commercial docs are wrongly
    # excluded by an exact edition=ce filter.
    is_dual_edition = is_ce and any(term in lower for term in _DUAL_MENTION_TERMS)

    # 2. Detect audience signal
    has_user = any(term in lower for term in _USER_TERMS)
    has_admin = any(term in lower for term in _ADMIN_TERMS)

    # Single primary edition; `editions` carries the full match set when dual.
    edition = "ce" if is_ce else "commercial"
    editions = ["commercial", "ce"] if is_dual_edition else None

    if has_user and not has_admin:
        return ProductContext(
            edition=edition,
            editions=editions,
            audience="user",
            confidence=1.0,
            reason="dual_edition_user" if is_dual_edition else "user_term_match",
        )

    if has_admin:
        return ProductContext(
            edition=edition,
            editions=editions,
            audience="admin",
            confidence=1.0,
            reason="dual_edition_admin" if is_dual_edition else "admin_term_match",
        )

    if is_dual_edition:
        # Both editions referenced but no audience signal — default to admin.
        return ProductContext(
            edition="commercial",
            editions=["commercial", "ce"],
            audience="admin",
            confidence=0.7,
            reason="dual_edition_admin_default",
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
