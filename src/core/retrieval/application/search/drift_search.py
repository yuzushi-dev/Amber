import asyncio
import logging
from typing import Any

# from src.core.services.retrieval import RetrievalService # Removed to avoid circular import
from src.core.generation.domain.provider_models import ProviderTier
from src.core.generation.domain.ports.provider_factory import ProviderFactoryPort
from src.core.generation.domain.ports.providers import LLMProviderPort

logger = logging.getLogger(__name__)

class DriftSearchService:
    """
    Implements DRIFT Search (Dynamic Reasoning and Inference with Flexible Traversal).
    Performs iterative context gathering and reasoning.
    """

    def __init__(
        self,
        retrieval_service: Any, # Avoid circular import with RetrievalService
        llm_provider: LLMProviderPort,
        max_iterations: int = 3,
        max_follow_ups: int = 3,
        provider_factory: ProviderFactoryPort | None = None,
    ):
        self.retrieval_service = retrieval_service
        self.llm = llm_provider
        self.max_iterations = max_iterations
        self.max_follow_ups = max_follow_ups
        self.factory = provider_factory

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
        3. Synthesis: Final grounded answer generation.
        """
        all_candidates = []
        follow_ups_history = []

        # 1. Primer Phase
        logger.info(f"DRIFT Primer for query: {query}")
        primer_results = await self.retrieval_service.retrieve(
            query=query,
            tenant_id=tenant_id,
            top_k=5
        )
        all_candidates.extend(primer_results.chunks)

        current_context = "\n".join([c["content"] for c in primer_results.chunks])

        from src.shared.kernel.runtime import get_settings
        from src.core.generation.application.llm_steps import resolve_llm_step_config

        settings = get_settings()
        tenant_config = tenant_config or {}
        followup_cfg = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="retrieval.drift_followups",
            settings=settings,
        )
        synthesis_cfg = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="retrieval.drift_synthesis",
            settings=settings,
        )

        for iteration in range(self.max_iterations):
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

            response = await followup_provider.generate(follow_up_prompt, **followup_kwargs)
            if "DONE" in response.upper():
                break

            questions = [q.strip() for q in response.split("\n") if q.strip()][:self.max_follow_ups]
            follow_ups_history.append({"iteration": iteration, "questions": questions})

            # 2. Expansion Phase: Execute sub-queries
            expansion_tasks = [
                self.retrieval_service.retrieve(query=q, tenant_id=tenant_id, top_k=3)
                for q in questions
            ]
            expansion_results = await asyncio.gather(*expansion_tasks)

            new_info_found = False
            for res in expansion_results:
                for chunk in res.chunks:
                    # Simple deduplication by content or ID
                    if not any(c["chunk_id"] == chunk["chunk_id"] for c in all_candidates):
                        all_candidates.append(chunk)
                        current_context += "\n" + chunk["content"]
                        new_info_found = True

            if not new_info_found:
                break

        # 3. Synthesis Phase
        synthesis_prompt = f"""
        You are an expert analyst. Answer the user query using the provided context.
        Query: {query}
        Context: {current_context}

        Provide a detailed, grounded answer with citations where appropriate.
        Answer:
        """

        synthesis_provider = self._get_provider(synthesis_cfg)
        synthesis_kwargs: dict[str, Any] = {}
        if synthesis_cfg.temperature is not None:
            synthesis_kwargs["temperature"] = synthesis_cfg.temperature
        if synthesis_cfg.seed is not None:
            synthesis_kwargs["seed"] = synthesis_cfg.seed

        final_answer = await synthesis_provider.generate(synthesis_prompt, **synthesis_kwargs)

        return {
            "answer": final_answer,
            "candidates": all_candidates,
            "follow_ups": follow_ups_history
        }

    def _get_provider(self, llm_cfg: Any) -> LLMProviderPort:
        if self.factory:
            return self.factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
        return self.llm
