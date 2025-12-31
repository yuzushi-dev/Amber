"""
Retrieval Service
=================

Unified retrieval pipeline combining vector search, caching, and reranking.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from src.api.schemas.query import SearchMode, QueryOptions
from src.core.cache.semantic_cache import CacheConfig, SemanticCache
from src.core.cache.result_cache import ResultCache, ResultCacheConfig
from src.core.providers.base import BaseRerankerProvider
from src.core.providers.factory import ProviderFactory
from src.core.services.embeddings import EmbeddingService
from src.core.query.parser import QueryParser
from src.core.query.rewriter import QueryRewriter
from src.core.query.decomposer import QueryDecomposer
from src.core.query.hyde import HyDEService
from src.core.query.router import QueryRouter
from src.core.query.models import StructuredQuery
from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore, SearchResult
from src.core.models.candidate import Candidate
from src.core.retrieval.search.vector import VectorSearcher
from src.core.retrieval.search.graph import GraphSearcher
from src.core.retrieval.search.entity import EntitySearcher
from src.core.retrieval.search.graph_traversal import GraphTraversalService
from src.core.retrieval.fusion import fuse_results
from src.core.retrieval.weights import get_adaptive_weights
from src.core.retrieval.global_search import GlobalSearchService
from src.core.retrieval.drift_search import DriftSearchService
from src.core.system.circuit_breaker import CircuitBreaker
from src.core.graph.neo4j_client import Neo4jClient
from src.core.observability.tracer import trace_span
from src.core.services.tuning import TuningService
from src.core.database.session import async_session_maker

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""

    chunks: list[dict[str, Any]]
    query: str
    tenant_id: str
    latency_ms: float
    cache_hit: bool = False
    reranked: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RetrievalConfig:
    """Retrieval service configuration."""

    # Search settings
    top_k: int = 10
    initial_k: int = 50  # Fetch more for reranking
    score_threshold: float | None = None

    # Reranking
    enable_reranking: bool = True
    rerank_model: str = "ms-marco-MiniLM-L-12-v2"

    # Caching
    enable_embedding_cache: bool = True
    enable_result_cache: bool = True

    # Milvus settings
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    embedding_dimensions: int = 1536


class RetrievalService:
    """
    Unified retrieval service combining:
    - Embedding generation with caching
    - Vector search in Milvus
    - Reranking with FlashRank
    - Result caching
    
    Usage:
        service = RetrievalService(
            openai_api_key="sk-...",
            config=RetrievalConfig(top_k=5),
        )
        result = await service.retrieve("What is GraphRAG?", tenant_id="default")
    """

    def __init__(
        self,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        redis_url: str = "redis://localhost:6379/0",
        config: RetrievalConfig | None = None,
        tuning_service: TuningService | None = None,
    ):
        self.config = config or RetrievalConfig()

        # Initialize embedding service
        factory = ProviderFactory(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )

        self.embedding_service = EmbeddingService(
            provider=factory.get_embedding_provider(),
        )

        # Initialize vector store
        milvus_config = MilvusConfig(
            host=self.config.milvus_host,
            port=self.config.milvus_port,
            dimensions=self.config.embedding_dimensions,
        )
        self.vector_store = MilvusVectorStore(milvus_config)

        # Initialize caches
        self.embedding_cache = SemanticCache(
            CacheConfig(
                redis_url=redis_url,
                enabled=self.config.enable_embedding_cache,
            )
        )
        self.result_cache = ResultCache(
            ResultCacheConfig(
                redis_url=redis_url,
                enabled=self.config.enable_result_cache,
            )
        )
        # Initialize Phase 5 services
        self.rewriter = QueryRewriter(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )
        self.decomposer = QueryDecomposer(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )
        self.hyde_service = HyDEService(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )
        self.router = QueryRouter(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )

        # Initialize Phase 6 services
        self.vector_searcher = VectorSearcher(self.vector_store)
        
        # We need a Neo4jClient for graph searchers
        # In a real app, this should be injected or retrieved from a registry
        self.neo4j_client = Neo4jClient()
        self.graph_searcher = GraphSearcher(self.neo4j_client)
        self.entity_searcher = EntitySearcher(self.vector_store) # Uses entity collection
        self.graph_traversal = GraphTraversalService(self.neo4j_client)
        
        # Advanced Search Modes
        llm = factory.get_llm_provider(tier=self.config.llm_tier if hasattr(self.config, 'llm_tier') else None)
        self.global_search = GlobalSearchService(self.vector_store, llm)
        self.drift_search = DriftSearchService(self, llm)
        
        # Resilience
        self.circuit_breaker = CircuitBreaker()

        # Initialize reranker
        self.reranker: BaseRerankerProvider | None = None
        if self.config.enable_reranking:
            try:
                self.reranker = factory.get_reranker_provider()
            except Exception as e:
                logger.warning(f"Reranker not available: {e}")

        # Initialize Tuning Service
        self.tuning = tuning_service or TuningService(session_factory=async_session_maker)

    @trace_span("RetrievalService.retrieve")
    async def retrieve(
        self,
        query: str,
        tenant_id: str,
        document_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
        include_trace: bool = False,
        options: QueryOptions | None = None,
        history: list[dict] | None = None,
    ) -> RetrievalResult:
        """
        Retrieve relevant chunks for a query with Phase 5 analysis.
        
        Pipeline:
        1. Contextual Rewriting (if enabled)
        2. Filter Extraction & Parsing
        3. Query Routing (SearchMode selection)
        4. Decomposition (if enabled)
        5. HyDE (if enabled)
        6. Search Execution (Vector/Graph/Global/DRIFT)
        7. Reranking
        8. Caching & Return
        """
        start_time = time.perf_counter()
        trace = []
        top_k = top_k or self.config.top_k
        options = options or QueryOptions()
        
        # Step 1: Contextual Rewriting
        processed_query = query
        if options.use_rewrite and history:
            processed_query = await self.rewriter.rewrite(query, history)
        
        structured_query = QueryParser.parse(processed_query)
        
        # Merge filters
        all_document_ids = list(set((document_ids or []) + (structured_query.document_ids or [])))
        all_filters = {**(filters or {})}
        if structured_query.tags:
            all_filters["tags"] = structured_query.tags
        # Date range filters could be added here

        # Step 3: Query Routing
        search_mode = await self.router.route(
            structured_query.cleaned_query,
            explicit_mode=options.search_mode
        )

        # Step 4 & 5: Search Execution based on Mode
        # For now, most modes fall back to vector search with optional HyDE/Decomposition
        # Phase 6 will implement specialized Global and DRIFT strategies.
        
        retrieval_start = time.perf_counter()
        
        # Step 4: Search Execution based on Mode
        retrieval_start = time.perf_counter()
        
        try:
            if search_mode == SearchMode.GLOBAL:
                res = await self.global_search.search(
                    query=structured_query.cleaned_query,
                    tenant_id=tenant_id
                )
                result = RetrievalResult(
                    chunks=[{"content": res["answer"], "chunk_id": "summary", "score": 1.0}],
                    query=query,
                    tenant_id=tenant_id,
                    latency_ms=0,
                    trace=trace + [{"step": "global_search", "sources": res["sources"]}]
                )
            elif search_mode == SearchMode.DRIFT:
                res = await self.drift_search.search(
                    query=structured_query.cleaned_query,
                    tenant_id=tenant_id
                )
                result = RetrievalResult(
                    chunks=res["candidates"],
                    query=query,
                    tenant_id=tenant_id,
                    latency_ms=0,
                )
            else:
                # Hybrid search for BASIC/LOCAL
                result = await self._execute_hybrid_search(
                    structured_query=structured_query,
                    tenant_id=tenant_id,
                    document_ids=all_document_ids,
                    filters=all_filters,
                    top_k=top_k,
                    options=options,
                    trace=trace
                )
        except Exception as e:
            logger.error(f"Retrieval failed for mode {search_mode}: {e}")
            # Fallback to simple vector search
            result = await self._execute_vector_search(
                structured_query=structured_query,
                tenant_id=tenant_id,
                document_ids=all_document_ids,
                filters=all_filters,
                top_k=top_k,
                options=options,
                trace=trace
            )
        
        # Record latency for circuit breaker
        total_latency = (time.perf_counter() - start_time) * 1000
        self.circuit_breaker.record_latency(total_latency)
        
        result.latency_ms = total_latency
        if not include_trace:
            result.trace = []
        else:
            result.trace = trace
            
        return result

    @trace_span("RetrievalService.hybrid_search")
    async def _execute_hybrid_search(
        self,
        structured_query: StructuredQuery,
        tenant_id: str,
        document_ids: list[str] | None,
        filters: dict[str, Any],
        top_k: int,
        options: QueryOptions,
        trace: list[dict],
    ) -> RetrievalResult:
        """Executes Hybrid (Vector + Graph) retrieval with RRF fusion."""
        step_start = time.perf_counter()
        
        # Parallel retrieval tasks
        query_text = structured_query.cleaned_query
        
        # 1. Vector Search
        # We need an embedding first
        embedding = await self.embedding_service.embed_single(query_text)
        
        vector_task = self.vector_searcher.search(
            query_vector=embedding,
            tenant_id=tenant_id,
            document_ids=document_ids,
            limit=self.config.initial_k
        )
        
        # 2. Entity + Graph Search
        entity_task = self.entity_searcher.search(
            query_vector=embedding,
            tenant_id=tenant_id,
            limit=5
        )
        
        # Run vector and entity search in parallel
        vector_results, entity_results = await asyncio.gather(vector_task, entity_task)
        
        graph_results = []
        if entity_results:
            entity_ids = [e["entity_id"] for e in entity_results]
            graph_results = await self.graph_searcher.search_by_entities(
                entity_ids=entity_ids,
                tenant_id=tenant_id,
                limit=self.config.initial_k
            )
            
            # 3. Optional Multi-hop Traversal (if not degraded)
            if not self.circuit_breaker.should_degrade:
                traversal_results = await self.graph_traversal.beam_search(
                    seed_entity_ids=entity_ids,
                    tenant_id=tenant_id,
                    depth=1, # Keep it shallow for performance
                    beam_width=3
                )
                graph_results.extend(traversal_results)

        # 4. Fusion
        groups = {
            "vector": vector_results,
            "graph": graph_results
        }
        
        # Adaptive weights with tenant overrides
        tenant_config = await self.tuning.get_tenant_config(tenant_id)
        weights = get_adaptive_weights(
            query_type=options.search_mode,
            tenant_config=tenant_config.get("weights", {})
        )
        fused = fuse_results(groups, weights=weights)
        
        # 5. Reranking (if not degraded)
        reranked_chunks = []
        reranked_flag = False
        
        if self.reranker and fused and not self.circuit_breaker.should_degrade:
            try:
                rerank_start = time.perf_counter()
                texts = [c.content for c in fused[:20]] # Rerank top 20
                rerank_res = await self.reranker.rerank(
                    query=query_text,
                    documents=texts,
                    top_k=top_k
                )
                
                # Map back to Candidates
                for item in rerank_res.results:
                    cand = fused[item.index]
                    cand.score = item.score
                    reranked_chunks.append(cand.to_dict())
                
                reranked_flag = True
                trace.append({
                    "step": "rerank",
                    "duration_ms": (time.perf_counter() - rerank_start) * 1000
                })
            except Exception as e:
                logger.warning(f"Reranking failed in hybrid mode: {e}")
                reranked_chunks = [c.to_dict() for c in fused[:top_k]]
        else:
            reranked_chunks = [c.to_dict() for c in fused[:top_k]]

        trace.append({
            "step": "hybrid_retrieval",
            "duration_ms": (time.perf_counter() - step_start) * 1000,
            "vector_count": len(vector_results),
            "graph_count": len(graph_results),
            "fused_count": len(fused)
        })

        return RetrievalResult(
            chunks=reranked_chunks,
            query=query_text,
            tenant_id=tenant_id,
            latency_ms=0,
            reranked=reranked_flag,
            trace=trace
        )

    @trace_span("RetrievalService.vector_search")
    async def _execute_vector_search(
        self,
        structured_query: StructuredQuery,
        tenant_id: str,
        document_ids: list[str] | None,
        filters: dict[str, Any],
        top_k: int,
        options: QueryOptions,
        trace: list[dict],
    ) -> RetrievalResult:
        """Helper to execute vector search with HyDE and Decomposition support."""
        
        # Handle Decomposition
        queries_to_run = [structured_query.cleaned_query]
        if options.use_decomposition:
            queries_to_run = await self.decomposer.decompose(structured_query.cleaned_query)

        all_chunks = []
        seen_chunk_ids = set()
        
        for q in queries_to_run:
            # Handle HyDE
            search_query = q
            if options.use_hyde:
                step_start = time.perf_counter()
                hypotheses = await self.hyde_service.generate_hypothesis(q)
                if hypotheses:
                    search_query = hypotheses[0]  # Use first hypothesis
                    trace.append({
                        "step": "hyde",
                        "duration_ms": (time.perf_counter() - step_start) * 1000,
                        "hypothesis_preview": search_query[:50] + "...",
                    })

            # Check result cache for this specific sub-query
            step_start = time.perf_counter()
            cache_filters = {"document_ids": document_ids, **(filters or {})}
            cached_result = await self.result_cache.get(search_query, tenant_id, cache_filters)

            if cached_result:
                sub_chunks = await self._fetch_chunks_by_ids(
                    cached_result.chunk_ids[:top_k],
                    cached_result.scores[:top_k],
                )
                for c in sub_chunks:
                    if c["chunk_id"] not in seen_chunk_ids:
                        all_chunks.append(c)
                        seen_chunk_ids.add(c["chunk_id"])
                continue

            # Get embedding
            query_embedding = await self.embedding_service.embed_single(search_query)

            # Vector search
            search_results = await self.vector_store.search(
                query_vector=query_embedding,
                tenant_id=tenant_id,
                document_ids=document_ids,
                limit=self.config.initial_k if self.reranker else top_k,
                score_threshold=self.config.score_threshold,
            )
            
            # Rerank
            reranked = False
            if self.reranker and len(search_results) > 0:
                step_start = time.perf_counter()
                try:
                    # Extract texts for reranking
                    texts = [r.metadata.get("content", "") for r in search_results]

                    rerank_result = await self.reranker.rerank(
                        query=search_query,
                        documents=texts,
                        top_k=top_k,
                    )

                    # Reorder results based on reranker scores
                    reranked_results = []
                    for item in rerank_result.results:
                        if item.index < len(search_results):
                            original = search_results[item.index]
                            reranked_results.append(
                                SearchResult(
                                    chunk_id=original.chunk_id,
                                    document_id=original.document_id,
                                    tenant_id=original.tenant_id,
                                    score=item.score,  # Use reranker score
                                    metadata=original.metadata,
                                )
                            )

                    search_results = reranked_results
                    reranked = True

                    trace.append({
                        "step": "rerank",
                        "duration_ms": (time.perf_counter() - step_start) * 1000,
                        "model": self.config.rerank_model,
                    })

                except Exception as e:
                    logger.warning(f"Reranking failed, using vector scores: {e}")
                    search_results = search_results[:top_k]

            else:
                search_results = search_results[:top_k]
            
            # Build chunks and cache
            sub_chunks_to_cache = []
            for r in search_results:
                chunk_data = {
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "score": r.score,
                    "content": r.metadata.get("content", ""),
                }
                sub_chunks_to_cache.append(chunk_data)
                if r.chunk_id not in seen_chunk_ids:
                    all_chunks.append(chunk_data)
                    seen_chunk_ids.add(r.chunk_id)

            # Cache results for this sub-query
            await self.result_cache.set(
                query=search_query,
                tenant_id=tenant_id,
                chunk_ids=[c["chunk_id"] for c in sub_chunks_to_cache],
                scores=[c["score"] for c in sub_chunks_to_cache],
                filters=cache_filters,
            )

        # Final sort and limit
        all_chunks.sort(key=lambda x: x["score"], reverse=True)
        final_chunks = all_chunks[:top_k]
        
        return RetrievalResult(
            chunks=final_chunks,
            query=structured_query.cleaned_query,
            tenant_id=tenant_id,
            latency_ms=0,  # Updated by caller
            trace=trace,
        )

    async def _fetch_chunks_by_ids(
        self,
        chunk_ids: list[str],
        scores: list[float],
    ) -> list[dict[str, Any]]:
        """Fetch full chunk data by IDs (from cache hit)."""
        # Fetch content from vector store
        chunks_data = await self.vector_store.get_chunks(chunk_ids)
        
        # Create lookup map
        chunk_map = {c["chunk_id"]: c for c in chunks_data}
        
        results = []
        for cid, score in zip(chunk_ids, scores):
            chunk = chunk_map.get(cid)
            if chunk:
                # Add score and ensure standardized format
                results.append({
                    "chunk_id": cid,
                    "document_id": chunk.get("document_id"),
                    "score": score,  # Use cached score
                    "content": chunk.get("content", ""),
                    "metadata": chunk.get("metadata", {}),
                })
                
        return results

    async def invalidate_cache(self, tenant_id: str) -> None:
        """Invalidate all caches for a tenant."""
        await self.result_cache.invalidate_tenant(tenant_id)

    @property
    def stats(self) -> dict[str, Any]:
        """Get service statistics."""
        return {
            "embedding_cache": self.embedding_cache.stats,
            "result_cache": self.result_cache.stats,
        }

    async def close(self) -> None:
        """Close all connections."""
        await self.vector_store.disconnect()
        await self.embedding_cache.close()
        await self.result_cache.close()
