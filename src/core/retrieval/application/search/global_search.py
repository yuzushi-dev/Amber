import asyncio
import logging
from typing import Any

from src.core.generation.domain.ports.provider_factory import ProviderFactoryPort
from src.core.generation.domain.ports.providers import LLMProviderPort
from src.core.generation.domain.provider_models import ProviderTier
from src.core.retrieval.domain.ports.vector_store_port import VectorStorePort

logger = logging.getLogger(__name__)


class GlobalSearchService:
    """
    Implements Global Search Map phase over community reports,
    yielding structured points linked to their backing documents.
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        llm_provider: LLMProviderPort,
        embedding_service: Any,
        map_chunk_size: int = 2000,
        provider_factory: ProviderFactoryPort | None = None,
        neo4j_client: Any = None,
    ):
        self.vector_store = vector_store
        self.llm = llm_provider
        self.embedding_service = embedding_service
        self.map_chunk_size = map_chunk_size
        self.factory = provider_factory
        self.neo4j_client = neo4j_client

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
        Execute Global Search (Map Phase Only):
        1. Retrieve relevant community reports via vector search.
        2. Map: Extract key points from each report.
        3. Resolve: Find original documents backing those communities.
        Returns candidates for the standard Generation (Reduce) phase.
        """
        # 1. Retrieve relevant community reports via vector search
        query_vector = await self.embedding_service.embed_single(query)

        reports = await self.vector_store.search(
            query_vector=query_vector,
            tenant_id=tenant_id,
            limit=max_reports,
            collection_name="community_embeddings",
        )

        if not reports:
            return {"candidates": []}

        # 2. Map Phase: Extract key points from each report
        from src.core.generation.application.llm_steps import resolve_llm_step_config
        from src.shared.kernel.runtime import get_settings

        settings = get_settings()
        tenant_config = tenant_config or {}
        map_cfg = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="retrieval.global_map",
            settings=settings,
        )

        map_tasks = []
        for report in reports:
            content = report.metadata.get("content", "")
            map_tasks.append(self._map_report(query, content, map_cfg))

        map_results = await asyncio.gather(*map_tasks)

        # 3. Resolve Original Documents
        community_ids = [r.chunk_id for r in reports]
        origins_map = await self._resolve_community_origins(community_ids, tenant_id)

        # 4. Pack into Candidates
        candidates = []
        for report, points in zip(reports, map_results, strict=True):
            if not points or points.strip() == "NONE":
                continue
            
            origin_doc_id = origins_map.get(report.chunk_id, "unknown")
            candidates.append({
                "chunk_id": report.chunk_id,
                "document_id": origin_doc_id,
                "content": f"Community Summary Findings:\n{points}",
                "score": float(report.score) if hasattr(report, "score") else 1.0,
                "metadata": {
                    "title": f"Community Insight Context",
                    "original_community": report.chunk_id
                }
            })

        return {"candidates": candidates}

    async def _resolve_community_origins(self, community_ids: list[str], tenant_id: str) -> dict[str, str]:
        """
        Finds the primary underlying document for each community using Neo4j.
        Returns a mapping of {community_id: document_id}.
        """
        if not self.neo4j_client or not community_ids:
            return {}
            
        try:
            query = """
            MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)-[:MENTIONS]->(e:Entity)-[:BELONGS_TO|IN_COMMUNITY]->(com:Community)
            WHERE com.id IN $community_ids AND com.tenant_id = $tenant_id
            WITH com.id AS community_id, d.id AS doc_id, count(e) AS entity_count
            ORDER BY entity_count DESC
            WITH community_id, collect(doc_id)[0] AS primary_doc_id
            RETURN community_id, primary_doc_id
            """
            
            results = await self.neo4j_client.execute_read(
                query, 
                {"community_ids": community_ids, "tenant_id": tenant_id}
            )
            
            return {row["community_id"]: row["primary_doc_id"] for row in results if row.get("community_id")}
        except Exception as e:
            logger.warning(f"Failed to resolve community origins: {e}")
            return {}

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
        res = await provider.generate(prompt, work_class="chat", **kwargs)
        return res.text or ""

    def _get_provider(self, llm_cfg: Any) -> LLMProviderPort:
        if self.factory:
            return self.factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
        return self.llm
