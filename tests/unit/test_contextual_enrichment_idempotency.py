"""
Regression tests for Issue #98 (contextual enrichment safety).

``ContextualEnricher.enrich_chunks`` stashes the pre-enrichment text in
``chunk.metadata_["original_content"]`` so the operation is reversible. That
assignment must be a ``setdefault``, not an overwrite: re-running enrichment
on an already-enriched chunk (idempotent retry, a backfill re-run, or any
other code path that writes the same key before this one runs) must never
clobber the one copy of the pristine text -- doing so makes it permanently
unrecoverable.

Also covers the partial/total enrichment-failure visibility fix: a run where
some or all chunks fail to enrich must log at WARNING, not silently at INFO
(this exact invisibility hid issue #84 for ~3 weeks).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.generation.application.llm_steps import LLMStepConfig
from src.core.ingestion.application.chunking.contextual import ContextualEnricher


def _chunk(content: str, metadata: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(content=content, metadata_=dict(metadata or {}))


@pytest.fixture(autouse=True)
def _stub_llm_step_resolution(monkeypatch):
    """Bypass tenant-config/model-registry resolution entirely: return a
    fixed step config and a fake provider whose .generate() is controlled
    per-test."""
    monkeypatch.setattr(
        "src.core.generation.application.llm_steps.resolve_llm_step_config",
        lambda **kwargs: LLMStepConfig(provider="ollama", model="test-model", temperature=0.0, seed=None),
    )


def _patch_provider(monkeypatch, generate: AsyncMock):
    monkeypatch.setattr(
        "src.core.generation.infrastructure.providers.factory.get_llm_provider",
        lambda **kwargs: SimpleNamespace(generate=generate),
    )


@pytest.mark.asyncio
async def test_enrich_chunks_preserves_pre_existing_original_content(monkeypatch, caplog):
    """A chunk that already carries ``original_content`` (from a prior
    prefixing step, or a previous enrichment pass) must keep that value
    untouched -- only ``context_prefix``/``content`` may change."""
    generate = AsyncMock(return_value=SimpleNamespace(content="New situating context."))
    _patch_provider(monkeypatch, generate)

    chunk = _chunk(
        "Section Header\n\nBody text.",
        metadata={"original_content": "Body text.", "start_char": 0, "end_char": 20},
    )

    enricher = ContextualEnricher()
    enriched = await enricher.enrich_chunks(
        [chunk], "full document text", tenant_config={}, settings=SimpleNamespace()
    )

    assert enriched == 1
    # The pristine text from BEFORE the section-header prefix was applied is
    # preserved -- not overwritten with the (already-prefixed) chunk.content.
    assert chunk.metadata_["original_content"] == "Body text."
    assert chunk.metadata_["context_prefix"] == "New situating context."
    assert chunk.content == "New situating context.\n\nSection Header\n\nBody text."


@pytest.mark.asyncio
async def test_enrich_chunks_sets_original_content_when_absent(monkeypatch):
    """The common case: no pre-existing original_content -- it's captured
    from the chunk's current content, same as before this fix."""
    generate = AsyncMock(return_value=SimpleNamespace(content="Context."))
    _patch_provider(monkeypatch, generate)

    chunk = _chunk("Plain chunk body.", metadata={"start_char": 0, "end_char": 17})

    enricher = ContextualEnricher()
    await enricher.enrich_chunks([chunk], "doc text", tenant_config={}, settings=SimpleNamespace())

    assert chunk.metadata_["original_content"] == "Plain chunk body."


@pytest.mark.asyncio
async def test_enrich_chunks_logs_warning_on_total_failure(monkeypatch, caplog):
    """Every chunk failing to enrich (enriched == 0) is the exact silent
    failure mode that hid issue #84 for weeks -- must warn, not info."""
    generate = AsyncMock(side_effect=RuntimeError("model retired"))
    _patch_provider(monkeypatch, generate)

    chunks = [_chunk("a"), _chunk("b")]
    enricher = ContextualEnricher()

    with caplog.at_level("WARNING", logger="src.core.ingestion.application.chunking.contextual"):
        enriched = await enricher.enrich_chunks(
            chunks, "doc text", tenant_config={}, settings=SimpleNamespace()
        )

    assert enriched == 0
    assert any("0/2 chunks enriched" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_enrich_chunks_logs_warning_on_partial_failure(monkeypatch, caplog):
    """Some chunks succeeding must not mask the ones that failed."""
    generate = AsyncMock(
        side_effect=[SimpleNamespace(content="ok"), RuntimeError("boom")]
    )
    _patch_provider(monkeypatch, generate)

    chunks = [_chunk("a"), _chunk("b")]
    enricher = ContextualEnricher()

    with caplog.at_level("WARNING", logger="src.core.ingestion.application.chunking.contextual"):
        enriched = await enricher.enrich_chunks(
            chunks, "doc text", tenant_config={}, settings=SimpleNamespace()
        )

    assert enriched == 1
    assert any("1/2 chunks enriched" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_enrich_chunks_logs_info_on_full_success(monkeypatch, caplog):
    """No noise when everything succeeds."""
    generate = AsyncMock(return_value=SimpleNamespace(content="ok"))
    _patch_provider(monkeypatch, generate)

    chunks = [_chunk("a"), _chunk("b")]
    enricher = ContextualEnricher()

    with caplog.at_level("INFO", logger="src.core.ingestion.application.chunking.contextual"):
        enriched = await enricher.enrich_chunks(
            chunks, "doc text", tenant_config={}, settings=SimpleNamespace()
        )

    assert enriched == 2
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert not warnings
