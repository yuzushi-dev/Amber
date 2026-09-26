import asyncio
import logging
from typing import Any

from src.core.generation.domain.ports.provider_factory import ProviderFactoryPort
from src.core.generation.domain.ports.providers import LLMProviderPort

# from src.core.services.retrieval import RetrievalService # Removed to avoid circular import
from src.core.generation.domain.provider_models import ProviderTier
from src.core.retrieval.application.query.parser import QueryParser
from src.core.tenants.application.query_scopes import QueryScopes
from src.shared.kernel.models.query import QueryOptions, SearchMode

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
        options: QueryOptions | None = None,
        tenant_config: dict | None = None,
        query_scopes: QueryScopes | None = None,
        document_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        for_generation: bool = False,
        include_trace: bool = False,
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
        all_candidates: list[dict[str, Any]] = []
        follow_ups_history: list[Any] = []
        trace: list[dict[str, Any]] = []
        reranking_ms = 0.0
        timed_out_stage: str | None = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        child_options = (options or QueryOptions()).model_copy(
            update={"search_mode": SearchMode.BASIC, "use_sufficiency_loop": False}
        )

        def retrieve_kwargs(child_query: str, top_k: int) -> dict[str, Any]:
            child_filters = dict(filters or {})
            if child_filters.get("tags") is None:
                child_tags = QueryParser.parse(child_query).tags
                if child_tags:
                    child_filters["tags"] = child_tags
            return {
                "query": child_query,
                "tenant_id": tenant_id,
                "top_k": top_k,
                "document_ids": document_ids,
                "filters": child_filters,
                "options": child_options,
                "query_scopes": query_scopes,
                "for_generation": for_generation,
                "include_trace": include_trace,
            }

        def collect_child_result(result: Any, phase: str, child_query: str) -> None:
            nonlocal reranking_ms
            reranking_ms += result.reranking_ms
            if include_trace:
                trace.extend(
                    {**step, "drift_phase": phase, "drift_query": child_query}
                    for step in result.trace
                )

        if document_ids is not None and not document_ids:
            return {
                "candidates": all_candidates,
                "follow_ups": follow_ups_history,
                "trace": trace,
                "reranking_ms": reranking_ms,
            }

        # 1. Primer Phase
        logger.info(f"DRIFT Primer for query: {query}")
        try:
            primer_results = await asyncio.wait_for(
                self.retrieval_service.retrieve(**retrieve_kwargs(query, 5)),
                timeout=max(0.0, deadline - loop.time()),
            )
        except TimeoutError:
            timed_out_stage = "primer"
            trace.append({"step": "drift_timeout", "stage": timed_out_stage})
            return {
                "candidates": all_candidates, "follow_ups": follow_ups_history,
                "trace": trace, "reranking_ms": reranking_ms,
                "timed_out_stage": timed_out_stage,
            }
        all_candidates.extend(primer_results.chunks)
        collect_child_result(primer_results, "primer", query)

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

        original_query = query  # Save for logging

        for iteration in range(self.max_iterations):
            # Check if we've exceeded our deadline
            current_time = loop.time()
            if current_time >= deadline:
                timed_out_stage = "generate"
                trace.append({"step": "drift_timeout", "stage": timed_out_stage})
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

            remaining = deadline - loop.time()
            if remaining <= 0:
                timed_out_stage = "generate"
                trace.append({"step": "drift_timeout", "stage": timed_out_stage})
                break
            try:
                followup_res = await asyncio.wait_for(
                    followup_provider.generate(
                        follow_up_prompt, work_class="chat", **followup_kwargs
                    ),
                    timeout=remaining,
                )
            except TimeoutError:
                timed_out_stage = "generate"
                trace.append({"step": "drift_timeout", "stage": timed_out_stage})
                break
            response = followup_res.text or ""
            if "DONE" in response.upper():
                break

            questions = [q.strip() for q in response.split("\n") if q.strip()][
                : self.max_follow_ups
            ]
            follow_ups_history.append({"iteration": iteration, "questions": questions})

            # 2. Expansion Phase: Execute sub-queries with timeout protection
            remaining = deadline - loop.time()
            if remaining <= 0:
                timed_out_stage = "expansion"
                trace.append({"step": "drift_timeout", "stage": timed_out_stage})
                logger.warning(
                    "DRIFT iteration %d: deadline reached before expansion", iteration
                )
                break

            expansion_tasks = [
                asyncio.wait_for(
                    self.retrieval_service.retrieve(**retrieve_kwargs(q, 3)),
                    timeout=remaining,
                )
                for q in questions
            ]

            # Wrap gather with timeout to catch individual call timeouts
            expansion_results = await asyncio.gather(*expansion_tasks, return_exceptions=True)

            if any(isinstance(result, asyncio.CancelledError) for result in expansion_results):
                raise asyncio.CancelledError
            if any(isinstance(result, TimeoutError) for result in expansion_results):
                timed_out_stage = "expansion"
                trace.append({"step": "drift_timeout", "stage": timed_out_stage})

            new_info_found = False
            for child_query, res in zip(questions, expansion_results, strict=True):
                if isinstance(res, BaseException):
                    continue
                collect_child_result(res, "expansion", child_query)
                for chunk in res.chunks:
                    # Simple deduplication by content or ID
                    if not any(c["chunk_id"] == chunk["chunk_id"] for c in all_candidates):
                        all_candidates.append(chunk)
                        current_context += "\n" + chunk["content"]
                        new_info_found = True

            if not new_info_found:
                break
            if timed_out_stage:
                break

        return {
            "candidates": all_candidates,
            "follow_ups": follow_ups_history,
            "trace": trace,
            "reranking_ms": reranking_ms,
            "timed_out_stage": timed_out_stage,
        }

    def _get_provider(self, llm_cfg: Any) -> LLMProviderPort:
        if self.factory:
            return self.factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
        return self.llm
