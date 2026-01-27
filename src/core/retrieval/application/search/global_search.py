import asyncio
import logging
from typing import Any

from src.core.generation.domain.provider_models import ProviderTier
from src.core.generation.domain.ports.provider_factory import ProviderFactoryPort
from src.core.generation.domain.ports.providers import LLMProviderPort
from src.core.retrieval.domain.ports.vector_store_port import VectorStorePort

logger = logging.getLogger(__name__)

class GlobalSearchService:
    """
    Implements Global Search using a Map-Reduce approach over community reports.
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        llm_provider: LLMProviderPort,
        embedding_service: Any,
        map_chunk_size: int = 2000,
        provider_factory: ProviderFactoryPort | None = None,
    ):
        self.vector_store = vector_store
        self.llm = llm_provider
        self.embedding_service = embedding_service
        self.map_chunk_size = map_chunk_size
        self.factory = provider_factory

    async def search(
        self,
        query: str,
        tenant_id: str,
        level: int = 1,
        max_reports: int = 10,
        relevance_threshold: float = 0.5,
        tenant_config: dict | None = None,
    ) -> dict[str, Any]:
        """
        Execute Global Search:
        1. Map: Score and summarize relevant community reports.
        2. Reduce: Synthesize the final answer.
        """
        # 1. Retrieve relevant community reports via vector search
        # Embed the query
        query_vector = await self.embedding_service.embed_single(query)
        
        # Community report embeddings were stored in Phase 4
        reports = await self.vector_store.search(
            query_vector=query_vector,
            tenant_id=tenant_id,
            limit=max_reports,
            collection_name="community_embeddings"
        )

        if not reports:
            return {"answer": "No relevant communities found for this query.", "sources": []}

        # 2. Map Phase: Extract key points from each report
        # In a real implementation, we would call the LLM for each report or batch them.
        from src.shared.kernel.runtime import get_settings
        from src.core.generation.application.llm_steps import resolve_llm_step_config

        settings = get_settings()
        tenant_config = tenant_config or {}
        map_cfg = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="retrieval.global_map",
            settings=settings,
        )
        reduce_cfg = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="retrieval.global_reduce",
            settings=settings,
        )

        map_tasks = []
        for report in reports:
            content = report.metadata.get("content", "")
            map_tasks.append(self._map_report(query, content, map_cfg))

        map_results = await asyncio.gather(*map_tasks)

        # 3. Reduce Phase: Synthesize final answer
        all_points = "\n".join([r for r in map_results if r])

        reduce_prompt = f"""
        You are an analyst synthesizing information from multiple community reports.
        User Query: {query}

        Key points extracted from relevant communities:
        {all_points}

        Based on the above points, provide a comprehensive, holistic answer to the user query.
        If the information is contradictory, highlight the different perspectives.
        Answer:
        """

        reduce_provider = self._get_provider(reduce_cfg)
        reduce_kwargs: dict[str, Any] = {}
        if reduce_cfg.temperature is not None:
            reduce_kwargs["temperature"] = reduce_cfg.temperature
        if reduce_cfg.seed is not None:
            reduce_kwargs["seed"] = reduce_cfg.seed

        final_answer = await reduce_provider.generate(reduce_prompt, **reduce_kwargs)

        return {
            "answer": final_answer,
            "sources": [r.chunk_id for r in reports] # Community IDs
        }

    async def _map_report(self, query: str, report_content: str, llm_cfg: Any) -> str:
        """LLM-based Map step to extract relevant points from a report."""
        prompt = f"""
        Extract key points relevant to the query from the following community report.
        Query: {query}
        Report: {report_content}

        Return a concise list of findings or 'NONE' if no relevant info.
        Findings:
        """
        provider = self._get_provider(llm_cfg)
        kwargs: dict[str, Any] = {}
        if llm_cfg.temperature is not None:
            kwargs["temperature"] = llm_cfg.temperature
        if llm_cfg.seed is not None:
            kwargs["seed"] = llm_cfg.seed
        return await provider.generate(prompt, **kwargs)

    def _get_provider(self, llm_cfg: Any) -> LLMProviderPort:
        if self.factory:
            return self.factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
        return self.llm
