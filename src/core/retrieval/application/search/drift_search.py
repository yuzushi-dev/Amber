import asyncio
import logging
from typing import Any

from src.core.generation.domain.ports.provider_factory import ProviderFactoryPort
from src.core.generation.domain.ports.providers import LLMProviderPort

# from src.core.services.retrieval import RetrievalService # Removed to avoid circular import
from src.core.generation.domain.provider_models import ProviderTier

logger = logging.getLogger(__name__)


class DriftSearchService:
    """
    Implements DRIFT Search (Dynamic Reasoning and Inference with Flexible Traversal).
    Performs iterative context gathering and reasoning.
    """

    def __init__(
        self,
        retrieval_service: Any,  # Avoid circular import with RetrievalService
        llm_provider: LLMProviderPort,
        max_iterations: int = 3,
        max_follow_ups: int = 3,
        provider_factory: ProviderFactoryPort | None = None,
        timeout_seconds: float = 25.0,
    ):
        self.retrieval_service = retrieval_service
        self.llm = llm_provider
        self.max_iterations = max_iterations
        self.max_follow_ups = max_follow_ups
        self.factory = provider_factory
        self.timeout_seconds = timeout_seconds

    async def search(
        self,
        query: str,
        tenant_id: str,
        options: Any | None = None,
        tenant_config: dict | None = None,
    ) -> dict[str, Any]:
        """
        Execute DRIFT Search:
        1. Primer: Initial retrieval and follow-up generation.
        2. Expansion: Iteratively retrieve for high-confidence follow-ups.

        Returns ``{"candidates": [...], "follow_ups": [...]}``; synthesis (LLM
        answer generation) is intentionally omitted here — the caller
        (``retrieve()``) only uses ``candidates`` and generation is handled
        downstream by GenerationService.
        """
        all_candidates = []
        follow_ups_history = []

        # 1. Primer Phase
        logger.info(f"DRIFT Primer for query: {query}")
        primer_results = await self.retrieval_service.retrieve(
            query=query, tenant_id=tenant_id, top_k=5
        )
        all_candidates.extend(primer_results.chunks)

        current_context = "\n".join([c["content"] for c in primer_results.chunks])

        from src.core.generation.application.llm_steps import resolve_llm_step_config
        from src.shared.kernel.runtime import get_settings

        settings = get_settings()
        tenant_config = tenant_config or {}
        followup_cfg = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="retrieval.drift_followups",
            settings=settings,
        )

        deadline = asyncio.get_event_loop().time() + self.timeout_seconds
        original_query = query  # Save for logging

        for iteration in range(self.max_iterations):
            # Check if we've exceeded our deadline
            current_time = asyncio.get_event_loop().time()
            if current_time >= deadline:
                logger.warning(
                    "DRIFT search timeout after %d iterations (%.1fs budget exceeded) query='%s'",
                    iteration, self.timeout_seconds, original_query
                )
                break

            # Generate follow-up questions to fill gaps
            follow_up_prompt = f"""
            Based on the query and current context, identify {self.max_follow_ups} specific questions
            that would help provide a more complete answer.
            Query: {query}
            Context: {current_context}

            Return ONLY the questions, one per line. If no more info is needed, return 'DONE'.
            Questions:
            """

            followup_provider = self._get_provider(followup_cfg)
            followup_kwargs: dict[str, Any] = {}
            if followup_cfg.temperature is not None:
                followup_kwargs["temperature"] = followup_cfg.temperature
            if followup_cfg.seed is not None:
                followup_kwargs["seed"] = followup_cfg.seed

            followup_res = await followup_provider.generate(
                follow_up_prompt, work_class="chat", **followup_kwargs
            )
            response = followup_res.text or ""
            if "DONE" in response.upper():
                break

            questions = [q.strip() for q in response.split("\n") if q.strip()][
                : self.max_follow_ups
            ]
            follow_ups_history.append({"iteration": iteration, "questions": questions})

            # 2. Expansion Phase: Execute sub-queries with timeout protection
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning(
                    "DRIFT iteration %d: deadline reached before expansion", iteration
                )
                break

            expansion_tasks = [
                asyncio.wait_for(
                    self.retrieval_service.retrieve(query=q, tenant_id=tenant_id, top_k=3),
                    timeout=remaining
                )
                for q in questions
            ]

            # Wrap gather with timeout to catch individual call timeouts
            expansion_results = await asyncio.gather(*expansion_tasks, return_exceptions=True)

            # Filter out any exception instances
            valid_results: list[Any] = [
                r for r in expansion_results
                if not isinstance(r, BaseException)
            ]

            new_info_found = False
            for res in valid_results:
                for chunk in res.chunks:
                    # Simple deduplication by content or ID
                    if not any(c["chunk_id"] == chunk["chunk_id"] for c in all_candidates):
                        all_candidates.append(chunk)
                        current_context += "\n" + chunk["content"]
                        new_info_found = True

            if not new_info_found:
                break

        return {
            "candidates": all_candidates,
            "follow_ups": follow_ups_history,
        }

    def _get_provider(self, llm_cfg: Any) -> LLMProviderPort:
        if self.factory:
            return self.factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
        return self.llm
