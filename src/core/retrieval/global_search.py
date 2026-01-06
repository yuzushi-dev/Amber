import asyncio
import logging
from typing import Any

from src.core.providers.base import BaseLLMProvider
from src.core.vector_store.milvus import MilvusVectorStore

logger = logging.getLogger(__name__)

class GlobalSearchService:
    """
    Implements Global Search using a Map-Reduce approach over community reports.
    """

    def __init__(
        self,
        vector_store: MilvusVectorStore,
        llm_provider: BaseLLMProvider,
        map_chunk_size: int = 2000
    ):
        self.vector_store = vector_store
        self.llm = llm_provider
        self.map_chunk_size = map_chunk_size

    async def search(
        self,
        query: str,
        tenant_id: str,
        level: int = 1,
        max_reports: int = 10,
        relevance_threshold: float = 0.5
    ) -> dict[str, Any]:
        """
        Execute Global Search:
        1. Map: Score and summarize relevant community reports.
        2. Reduce: Synthesize the final answer.
        """
        # 1. Retrieve relevant community reports via vector search
        # Community report embeddings were stored in Phase 4
        reports = await self.vector_store.search(
            query_vector=None, # Will be filled by embedding the 'query'
            query_text=query,
            tenant_id=tenant_id,
            limit=max_reports,
            collection_name="community_embeddings"
        )

        if not reports:
            return {"answer": "No relevant communities found for this query.", "sources": []}

        # 2. Map Phase: Extract key points from each report
        # In a real implementation, we would call the LLM for each report or batch them.
        map_tasks = []
        for report in reports:
            content = report.metadata.get("content", "")
            map_tasks.append(self._map_report(query, content))

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

        final_answer = await self.llm.generate(reduce_prompt)

        return {
            "answer": final_answer,
            "sources": [r.chunk_id for r in reports] # Community IDs
        }

    async def _map_report(self, query: str, report_content: str) -> str:
        """LLM-based Map step to extract relevant points from a report."""
        prompt = f"""
        Extract key points relevant to the query from the following community report.
        Query: {query}
        Report: {report_content}

        Return a concise list of findings or 'NONE' if no relevant info.
        Findings:
        """
        return await self.llm.generate(prompt)
