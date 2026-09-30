"""UsageTracker: subscription list-price estimate + caller attribution (ZTD-2054)."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.admin_ops.application.usage_tracker import (
    UsageTracker,
    _normalize_model,
    estimate_subscription_cost,
)
from src.core.generation.domain.provider_models import TokenUsage
from src.shared.context import set_extra_context


def _tracker():
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield session

    return UsageTracker(factory), session


def _saved(session):
    return session.add.call_args.args[0]


def test_normalize_model_strips_cloud_and_latest():
    assert _normalize_model("gemma4:31b-cloud") == "gemma4:31b"
    assert _normalize_model("glm-5.2:cloud") == "glm-5.2"
    assert _normalize_model("nomic-embed-text:latest") == "nomic-embed-text"
    assert _normalize_model("gemma4:31b") == "gemma4:31b"


def test_estimate_is_per_million_tokens():
    # gemma4:31b = $0.13 in / $0.38 out per 1M tokens
    cost = estimate_subscription_cost("gemma4:31b-cloud", TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000))
    assert cost == pytest.approx(0.51)
    assert estimate_subscription_cost("unknown-model", TokenUsage(input_tokens=10, output_tokens=10)) is None


def test_env_override_extends_table(monkeypatch):
    monkeypatch.setenv("AMBER_USAGE_PRICES_JSON", '{"glm-5.2:cloud": [1.0, 2.0]}')
    cost = estimate_subscription_cost("glm-5.2:cloud", TokenUsage(input_tokens=1_000_000, output_tokens=500_000))
    assert cost == pytest.approx(2.0)
    monkeypatch.setenv("AMBER_USAGE_PRICES_JSON", "not json")
    assert estimate_subscription_cost("gemma4:31b", TokenUsage(input_tokens=1_000_000, output_tokens=0)) == pytest.approx(0.13)


@pytest.mark.asyncio
async def test_generation_zero_cost_gets_estimate_and_caller():
    tracker, session = _tracker()
    set_extra_context({"api_key_name": "openwebui", "x_user_id": None})
    await tracker.record_usage(
        tenant_id="default", operation="generation", provider="ollama_cloud_3",
        model="gemma4:31b-cloud", usage=TokenUsage(input_tokens=1000, output_tokens=100),
        metadata={"response_id": "r1"},
    )
    row = _saved(session)
    assert row.cost == pytest.approx((1000 * 0.13 + 100 * 0.38) / 1_000_000)
    assert row.metadata_json == {"api_key_name": "openwebui", "response_id": "r1", "cost_kind": "subscription_equiv"}


@pytest.mark.asyncio
async def test_real_cost_and_embeddings_untouched_unpriced_flagged():
    tracker, session = _tracker()
    set_extra_context(None)
    await tracker.record_usage(
        tenant_id="default", operation="generation", provider="anthropic", model="claude-x",
        usage=TokenUsage(input_tokens=10, output_tokens=10), cost=0.5,
    )
    assert _saved(session).cost == 0.5
    assert _saved(session).metadata_json == {}

    await tracker.record_usage(
        tenant_id="default", operation="embedding", provider="ollama", model="nomic-embed-text",
        usage=TokenUsage(input_tokens=10, output_tokens=0),
    )
    assert _saved(session).cost == 0.0
    assert "cost_kind" not in _saved(session).metadata_json

    await tracker.record_usage(
        tenant_id="default", operation="generation", provider="ollama", model="glm-5.2:cloud",
        usage=TokenUsage(input_tokens=10, output_tokens=10),
    )
    assert _saved(session).cost == 0.0
    assert _saved(session).metadata_json == {"cost_kind": "unpriced"}
