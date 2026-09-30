"""The contextual header must be able to name the document: the scoped excerpt
usually drops the page title, so short chunks ("valid for Ubuntu 24.04") got a
context that never said which article they belong to."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.generation.application.llm_steps import LLMStepConfig
from src.core.ingestion.application.chunking.contextual import (
    ContextualEnricher,
    document_title_from_filename,
)


@pytest.mark.parametrize(
    ("filename", "title"),
    [
        (
            "27632952006812-Hide-the-View-Mail-Option-in-Acme-Mail-Admin-Panel.html",
            "Hide the View Mail Option in Acme Mail Admin Panel",
        ),
        (
            "AcmeMail_Docs_upgrade_changelogs__changelog-25.12.0.html",
            "AcmeMail Docs upgrade changelogs changelog 25.12.0",
        ),
        ("partner-handbook-HB1.html", "partner handbook HB1"),
        ("default/doc_x/Guide.pdf", "Guide"),
        ("README", "README"),
        (None, None),
        ("", None),
    ],
)
def test_document_title_from_filename(filename, title):
    assert document_title_from_filename(filename) == title


@pytest.mark.asyncio
async def test_prompt_carries_document_title(monkeypatch):
    monkeypatch.setattr(
        "src.core.generation.application.llm_steps.resolve_llm_step_config",
        lambda **kwargs: LLMStepConfig(
            provider="ollama", model="test-model", temperature=0.0, seed=None
        ),
    )
    generate = AsyncMock(return_value=SimpleNamespace(content="ctx"))
    monkeypatch.setattr(
        "src.core.generation.infrastructure.providers.factory.get_llm_provider",
        lambda **kwargs: SimpleNamespace(generate=generate),
    )
    enricher = ContextualEnricher()
    chunk = SimpleNamespace(
        content="Valid for Ubuntu 24.04.", metadata_={"start_char": 0, "end_char": 23}
    )

    await enricher.enrich_chunks(
        [chunk],
        "Valid for Ubuntu 24.04.",
        tenant_config={},
        settings=SimpleNamespace(),
        document_title="Hide the View Mail Option",
    )
    prompt = generate.await_args.kwargs["prompt"]
    assert "<document_title>Hide the View Mail Option</document_title>" in prompt
    assert "Start with the document title." in prompt

    await enricher.enrich_chunks(
        [SimpleNamespace(content="x", metadata_={})],
        "x",
        tenant_config={},
        settings=SimpleNamespace(),
    )
    prompt = generate.await_args.kwargs["prompt"]
    assert "<document_title>" not in prompt and "document title" not in prompt
    assert prompt.startswith("<document_excerpt>")
