"""
Unit tests for ProductContextResolver — deterministic query-time taxonomy inference.
"""

from src.core.retrieval.application.query.product_context_resolver import (
    ProductContext,
    resolve_product_context,
)

# ---------------------------------------------------------------------------
# Admin / commercial defaults
# ---------------------------------------------------------------------------

def test_delegate_admin_resolves_commercial_admin():
    ctx = resolve_product_context("How do delegate admins work?")
    assert ctx.edition == "commercial"
    assert ctx.audience == "admin"


def test_domain_config_resolves_admin():
    ctx = resolve_product_context("How do I configure a new domain?")
    assert ctx.audience == "admin"


def test_install_resolves_admin():
    ctx = resolve_product_context("How do I install Acme Mail?")
    assert ctx.audience == "admin"


def test_ambiguous_admin_defaults_to_commercial():
    ctx = resolve_product_context("How do I configure backup schedules?")
    assert ctx.edition == "commercial"
    assert ctx.audience == "admin"


# ---------------------------------------------------------------------------
# CE explicit
# ---------------------------------------------------------------------------

def test_ce_abbreviation_resolves_ce():
    ctx = resolve_product_context("How do delegate admins work in CE?")
    assert ctx.edition == "ce"
    assert ctx.audience == "admin"


def test_community_edition_phrase_resolves_ce():
    ctx = resolve_product_context("How do I configure domains in Acme Mail Community Edition?")
    assert ctx.edition == "ce"
    assert ctx.audience == "admin"


def test_acme_mail_ce_phrase_resolves_ce():
    ctx = resolve_product_context("How to upgrade Acme Mail CE on Ubuntu?")
    assert ctx.edition == "ce"


# ---------------------------------------------------------------------------
# User intent
# ---------------------------------------------------------------------------

def test_webmail_resolves_user():
    ctx = resolve_product_context("How do I use message search in chat?")
    assert ctx.audience == "user"


def test_calendar_resolves_user():
    ctx = resolve_product_context("How do I manage my calendar appointments?")
    assert ctx.audience == "user"


def test_send_email_resolves_user():
    ctx = resolve_product_context("How do I send an email using webmail?")
    assert ctx.audience == "user"
    assert ctx.edition == "commercial"


# ---------------------------------------------------------------------------
# CE user
# ---------------------------------------------------------------------------

def test_ce_user_query():
    ctx = resolve_product_context("How do I use the webmail in Acme Mail CE?")
    assert ctx.edition == "ce"
    assert ctx.audience == "user"


# ---------------------------------------------------------------------------
# Dual-edition mention (query references BOTH commercial and CE)
# ---------------------------------------------------------------------------

def test_dual_edition_2fa_query_matches_both_editions():
    # Regression: this query previously resolved to ce-only, excluding the
    # commercial 2FA docs and yielding "I don't have documentation".
    ctx = resolve_product_context(
        "How the 2FA work in Carbonio? Is there a similar feature in Carbonio CE?"
    )
    assert ctx.editions == ["commercial", "ce"]
    # Primary scalar edition stays populated for backward-compat callers.
    assert ctx.edition in ("commercial", "ce")


def test_dual_edition_difference_query_matches_both():
    ctx = resolve_product_context(
        "What is the difference between backup in Acme Mail and in CE?"
    )
    assert ctx.editions == ["commercial", "ce"]


def test_plain_ce_query_is_not_dual_edition():
    # No contrastive marker -> stays ce-only (editions is None).
    ctx = resolve_product_context("How do I configure domains in Acme Mail CE?")
    assert ctx.edition == "ce"
    assert ctx.editions is None


# ---------------------------------------------------------------------------
# Ambiguous / low-confidence produces partial, not hard failure
# ---------------------------------------------------------------------------

def test_ambiguous_query_returns_context_object():
    ctx = resolve_product_context("Tell me about Acme Mail")
    assert isinstance(ctx, ProductContext)
    assert ctx.edition in ("commercial", "ce", "unknown")
    assert ctx.audience in ("admin", "user", "unknown")


def test_empty_query_does_not_raise():
    ctx = resolve_product_context("")
    assert isinstance(ctx, ProductContext)


# ---------------------------------------------------------------------------
# Confidence and reason fields
# ---------------------------------------------------------------------------

def test_explicit_ce_has_higher_confidence_than_unknown():
    ce_ctx = resolve_product_context("Acme Mail CE backup configuration")
    vague_ctx = resolve_product_context("Tell me something")
    assert ce_ctx.confidence >= vague_ctx.confidence


def test_result_has_required_fields():
    ctx = resolve_product_context("How do I install Acme Mail?")
    assert hasattr(ctx, "edition")
    assert hasattr(ctx, "audience")
    assert hasattr(ctx, "confidence")
    assert hasattr(ctx, "reason")
