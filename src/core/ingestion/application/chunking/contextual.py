"""
Contextual Enricher
===================

Contextual retrieval (Anthropic-style): for each chunk, an LLM generates a short
context that situates the chunk within the source document. The context is
prepended to the chunk content BEFORE embedding (dense and sparse), so both
vector and keyword search see the disambiguated text. The enriched content is
also what retrieval returns, which helps the reader resolve pronouns and
entity references that the raw chunk leaves dangling.

Reference: https://www.anthropic.com/news/contextual-retrieval
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

CONTEXT_PROMPT = """<document_excerpt>
{document_excerpt}
</document_excerpt>

Here is the chunk we want to situate within the document above:
<chunk>
{chunk_content}
</chunk>

Write a short context (1-2 sentences, max 80 tokens) that situates this chunk \
within the overall document for the purposes of improving search retrieval of \
the chunk. Name the specific entity, section or topic the chunk belongs to. \
Answer ONLY with the context, nothing else."""


class ContextualEnricher:
    """
    Enriches chunks in place with an LLM-generated situating context.

    The context is prepended to ``chunk.content``; the original text and the
    generated context are kept in ``chunk.metadata_`` so the operation is
    inspectable and reversible.
    """

    def __init__(
        self,
        *,
        window_chars: int = 6000,
        max_concurrency: int = 8,
        max_context_chars: int = 600,
    ):
        self.window_chars = window_chars
        self.max_concurrency = max_concurrency
        self.max_context_chars = max_context_chars

    def _excerpt_for(self, document_text: str, start_char: int, end_char: int) -> str:
        """Window of the source document around the chunk (captures governing headers)."""
        lo = max(0, start_char - self.window_chars)
        hi = min(len(document_text), end_char + self.window_chars)
        return document_text[lo:hi]

    async def generate_context(
        self,
        provider: Any,
        chunk_content: str,
        document_excerpt: str,
        *,
        temperature: float = 0.0,
    ) -> str | None:
        """Single LLM call -> short situating context, or None on failure."""
        prompt = CONTEXT_PROMPT.format(
            document_excerpt=document_excerpt,
            chunk_content=chunk_content,
        )
        try:
            response = await provider.generate(prompt=prompt, temperature=temperature)
            text = (getattr(response, "content", None) or getattr(response, "text", "") or "").strip()
            if not text:
                return None
            return text[: self.max_context_chars]
        except Exception as e:
            logger.warning(f"Chunk contextualization failed: {e}")
            return None

    async def enrich_chunks(
        self,
        chunks: list[Any],
        document_text: str,
        *,
        tenant_config: dict[str, Any],
        settings: Any,
    ) -> int:
        """
        Enrich ``chunks`` (domain Chunk objects) in place. Returns the number of
        chunks actually enriched. Failures leave the chunk untouched.
        """
        from src.core.generation.application.llm_steps import resolve_llm_step_config
        from src.core.generation.infrastructure.providers.base import ProviderTier
        from src.core.generation.infrastructure.providers.factory import get_llm_provider

        llm_config = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="ingestion.chunk_context",
            settings=settings,
        )
        provider = get_llm_provider(
            provider_name=llm_config.provider,
            model=llm_config.model,
            tier=ProviderTier.ECONOMY,
        )

        semaphore = asyncio.Semaphore(self.max_concurrency)
        enriched = 0

        async def _one(chunk: Any) -> None:
            nonlocal enriched
            meta = chunk.metadata_ or {}
            start = int(meta.get("start_char") or 0)
            end = int(meta.get("end_char") or start + len(chunk.content))
            excerpt = self._excerpt_for(document_text, start, end)
            async with semaphore:
                context = await self.generate_context(
                    provider,
                    chunk.content,
                    excerpt,
                    temperature=llm_config.temperature or 0.0,
                )
            if not context:
                return
            meta["context_prefix"] = context
            meta["original_content"] = chunk.content
            chunk.metadata_ = dict(meta)
            chunk.content = f"{context}\n\n{chunk.content}"
            enriched += 1

        await asyncio.gather(*(_one(c) for c in chunks))
        logger.info(
            "Contextual enrichment: %d/%d chunks enriched (model=%s)",
            enriched,
            len(chunks),
            llm_config.model,
        )
        return enriched
