"""
Retrieval Service
=================

Unified retrieval pipeline combining vector search, caching, and reranking.
"""

import inspect
import logging
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from src.core.admin_ops.application.tuning_service import TuningService
from src.core.cache.result_cache import ResultCache, ResultCacheConfig
from src.core.cache.semantic_cache import CacheConfig, SemanticCache
from src.core.generation.domain.ports.provider_factory import (
    build_provider_factory,
    get_provider_factory,
)
from src.core.generation.domain.ports.providers import RerankerProviderPort
from src.core.ingestion.domain.ports.document_repository import DocumentRepository
from src.core.retrieval.application.embeddings_service import EmbeddingService
from src.core.retrieval.application.query.decomposer import QueryDecomposer
from src.core.retrieval.application.query.hyde import HyDEService
from src.core.retrieval.application.query.models import StructuredQuery
from src.core.retrieval.application.query.parser import QueryParser
from src.core.retrieval.application.query.product_context_resolver import (
    resolve_product_context,
)
from src.core.retrieval.application.query.rewriter import QueryRewriter
from src.core.retrieval.application.query.router import QueryRouter
from src.core.retrieval.application.query.sufficiency import SufficiencyEvaluator
from src.core.retrieval.application.search.drift_search import DriftSearchService
from src.core.retrieval.application.search.global_search import GlobalSearchService
from src.core.retrieval.application.search.vector import VectorSearcher
from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService
from src.core.retrieval.domain.ports.graph_store_port import GraphStorePort
from src.core.retrieval.domain.ports.vector_store_port import SearchResult, VectorStorePort
from src.core.system.circuit_breaker import LatencyMonitor
from src.core.tenants.application.active_vector_collection import resolve_active_vector_collection
from src.core.tenants.application.query_scopes import QueryScopes, resolve_query_scopes
from src.shared.kernel.models.query import QueryOptions, SearchMode
from src.shared.kernel.observability import trace_span
from src.shared.kernel.runtime import get_settings as _get_settings

logger = logging.getLogger(__name__)

_ARTICLE_REFERENCE_PATTERN = re.compile(
    r"(?:\b(?:articles?|articol[oi]|kb)\b[\s:#-]*([0-9]{8,})(?![A-Za-z0-9_])|"
    r"/articles/([0-9]{8,})(?![A-Za-z0-9_]))",
    re.IGNORECASE,
)


def _extract_article_reference(query: str) -> str | None:
    match = _ARTICLE_REFERENCE_PATTERN.search(query)
    return next((number for number in match.groups() if number), None) if match else None


def _validated_rerank_results(
    items: Any,
    *,
    input_count: int,
    top_k: int,
) -> list[tuple[int, float]] | None:
    """Validate a complete reranker selection before any candidate is changed."""
    if not isinstance(items, list) or len(items) != min(top_k, input_count):
        return None

    validated: list[tuple[int, float]] = []
    seen_indices: set[int] = set()
    try:
        for item in items:
            index = item.index
            score_value = item.score
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
                or index >= input_count
                or index in seen_indices
                or isinstance(score_value, bool)
            ):
                return None
            score = float(score_value)
            if not math.isfinite(score):
                return None
            seen_indices.add(index)
            validated.append((index, score))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return validated


_RERANK_TIMING_FIELDS = (
    "ranker_load_ms",
    "executor_queue_ms",
    "ranker_execution_ms",
    "postprocess_ms",
)

# ponytail: fixed caps on continuation chunks per generation context (multi-chunk
# documents / sufficiency gap hits); make them RetrievalConfig fields only if
# tuning per tenant is ever needed.
MAX_DOCUMENT_CONTINUATIONS = 4
MAX_GAP_CONTINUATIONS = 3
# At most this many gap queries run per sufficiency round, and at most this many
# new chunks are admitted per round (one slot per gap query, round-robin).
SUFFICIENCY_GAPS_PER_ROUND = 3  # gap queries (searches + reranks) per round
# Gap hits admitted per round (round-robin across that round's gap queries). 6 lets each
# of 3 gap queries contribute 2 hits: +10/124 key facts in the 2026-09-26 replay.
SUFFICIENCY_GAP_HITS_PER_ROUND = 6
# Gap hits whose reranker score (against their own gap query) falls below this are
# off-topic noise and are not admitted. Calibrated on FlashRank ms-marco-MiniLM-L-12-v2:
# legitimate gap hits scored >= 0.61; the 0.25-0.6 band held only irrelevant hits in a
# 64-run held-out benchmark. Recalibrate if the reranker model changes.
# ponytail: fixed threshold; it only catches off-topic noise, not lexical false
# positives (MiniLM saturates on word overlap).
SUFFICIENCY_GAP_MIN_SCORE = 0.6


def _provider_rerank_timings(result: Any) -> dict[str, float]:
    """Expose only safe numeric timing metadata from a reranker result."""
    metadata = getattr(result, "metadata", None)
    if not isinstance(metadata, dict):
        return {}

    timings: dict[str, float] = {}
    for key in _RERANK_TIMING_FIELDS:
        value = metadata.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        elapsed = float(value)
        if math.isfinite(elapsed) and elapsed >= 0:
            timings[key] = elapsed
    return timings


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""

    chunks: list[dict[str, Any]]
    query: str
    tenant_id: str
    latency_ms: float
    cache_hit: bool = False
    search_mode: str = "unknown"
    router_latency_ms: float = 0.0
    reranked: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
    reranking_ms: float = 0.0


@dataclass(frozen=True)
class VectorSearchTarget:
    """Resolved vector search target for a tenant-owned collection."""

    tenant_id: str
    collection_name: str
    document_ids: list[str] | None = None
    # Blocklist of non-READY document IDs (with indexed chunks) to exclude.
    # Resolved independently of ACLs - see _list_non_ready_document_ids_with_chunks.
    exclude_document_ids: list[str] | None = None


@dataclass(frozen=True)
class GraphSearchTarget:
    """Resolved graph search target for a tenant-owned graph scope."""

    tenant_id: str
    allowed_doc_ids: list[str] | None = None
    # Blocklist of non-READY document IDs (with indexed chunks) to exclude.
    # Resolved independently of ACLs - see _list_non_ready_document_ids_with_chunks.
    excluded_doc_ids: list[str] | None = None


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
    # Relevance floor applied AFTER reranking, on the reranker's own scale - the
    # only scale available downstream of both the dense and the hybrid path
    # (see the scale note in _search_vector_targets_hybrid). Measured on the prod
    # corpus with ms-marco-MiniLM-L-12-v2: on-topic chunks score >= 0.82, chunks
    # for a query with no coverage score ~0.0, so anything in 0.1-0.5 separates
    # them with a wide margin. None = disabled (no chunk dropped).
    rerank_score_floor: float | None = None

    # Hybrid Search - DISABLED: Milvus 2.5.x has intermittent type mismatch errors with hybrid AnnSearchRequest
    enable_hybrid: bool = False

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
        document_repository: DocumentRepository,
        # Injected clients via Ports
        vector_store: VectorStorePort,
        neo4j_client: GraphStorePort,  # Using GraphStorePort protocol, keeping name for compatibility if possible, or rename?
        # neo4j_client is used by GraphSearcher etc. They expect a client like object.
        # If GraphStorePort matches Neo4jClient signature, we are good.
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        ollama_base_url: str | None = None,
        default_embedding_provider: str | None = None,
        default_embedding_model: str | None = None,
        redis_url: str = "redis://localhost:6379/0",
        config: RetrievalConfig | None = None,
        tuning_service: TuningService | None = None,
        sparse_embedding: SparseEmbeddingService | None = None,
    ):
        self.config = config or RetrievalConfig()

        self.document_repository = document_repository
        self.neo4j_client = neo4j_client
        self.vector_store = vector_store

        # Initialize embedding service
        if (
            openai_api_key
            or anthropic_api_key
            or ollama_base_url
            or default_embedding_provider
            or default_embedding_model
        ):
            # This factory also serves the rewriter/decomposer/HyDE/router, so it
            # must carry the ollama_cloud credentials a tenant llm_steps override
            # may route them to.
            try:
                runtime_settings = _get_settings()
            except RuntimeError:
                runtime_settings = None
            factory = build_provider_factory(
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                ollama_base_url=ollama_base_url,
                default_embedding_provider=default_embedding_provider,
                default_embedding_model=default_embedding_model,
                ollama_cloud_base_url=getattr(runtime_settings, "ollama_cloud_base_url", None),
                ollama_cloud_api_keys=getattr(runtime_settings, "ollama_cloud_api_keys", None),
            )
        else:
            factory = get_provider_factory()

        self.embedding_service = EmbeddingService(
            provider=factory.get_embedding_provider(
                provider_name=default_embedding_provider,
                model=default_embedding_model,
            ),
            model=default_embedding_model,
        )

        self.sparse_embedding = sparse_embedding
        if self.config.enable_hybrid and not self.sparse_embedding:
            self.sparse_embedding = SparseEmbeddingService()

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
            provider_factory=factory,
        )
        self.decomposer = QueryDecomposer(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            provider_factory=factory,
        )
        self.hyde_service = HyDEService(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            provider_factory=factory,
        )
        self.router = QueryRouter(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            provider_factory=factory,
        )
        self.sufficiency_evaluator = SufficiencyEvaluator(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            provider_factory=factory,
        )

        self.vector_searcher = VectorSearcher(self.vector_store)

        # Advanced Search Modes
        llm = factory.get_llm_provider(
            tier=self.config.llm_tier if hasattr(self.config, "llm_tier") else None
        )
        self.global_search = GlobalSearchService(
            self.vector_store,
            llm,
            embedding_service=self.embedding_service,
            provider_factory=factory,
            neo4j_client=self.neo4j_client,
        )
        self.drift_search = DriftSearchService(self, llm, provider_factory=factory)

        # Resilience
        self.circuit_breaker = LatencyMonitor()

        # Initialize reranker
        self.reranker: RerankerProviderPort | None = None
        if self.config.enable_reranking:
            try:
                self.reranker = factory.get_reranker_provider()
            except Exception as e:
                logger.warning(f"Reranker not available: {e}")

        # Initialize Tuning Service
        # Initialize Tuning Service
        # Requires Session. If not provided, we skip or require injection.
        # Ideally TuningService should be refactored too, but for now we rely on injection.
        self.tuning = tuning_service
        # or TuningService(session_factory=async_session_maker) - REMOVED DEFAULT

    async def _get_effective_tenant_config(self, tenant_id: str) -> dict[str, Any]:
        """Resolve effective tenant config, preserving compatibility with older test stubs."""
        if not self.tuning:
            return {}

        effective_getter = getattr(self.tuning, "get_effective_tenant_config", None)
        if callable(effective_getter):
            return await effective_getter(tenant_id)

        return await self.tuning.get_tenant_config(tenant_id)

    async def _resolve_active_collection(self, tenant_id: str) -> str:
        """Resolve the active vector collection for a tenant."""
        if self.tuning:
            config = await self._get_effective_tenant_config(tenant_id)
            return resolve_active_vector_collection(tenant_id, config)
        logger.warning("TuningService not provided; falling back to default active collection")
        return resolve_active_vector_collection(tenant_id, {})

    async def _list_visible_document_ids(
        self,
        viewer_tenant_id: str,
        owner_tenant_id: str,
        candidate_document_ids: list[str] | None,
        group_ids: list[str] | None = None,
        enforce_groups: bool = False,
    ) -> list[str]:
        """List visible document IDs for a viewer, failing closed for shared scopes if unsupported."""
        visibility_getter = getattr(self.document_repository, "list_visible_document_ids", None)
        if not callable(visibility_getter):
            if owner_tenant_id == viewer_tenant_id:
                return candidate_document_ids or []
            logger.warning(
                "DocumentRepository does not implement list_visible_document_ids; denying shared vector scope owner=%s viewer=%s",
                owner_tenant_id,
                viewer_tenant_id,
            )
            return []

        result = visibility_getter(
            viewer_tenant_id=viewer_tenant_id,
            owner_tenant_id=owner_tenant_id,
            candidate_document_ids=candidate_document_ids,
            group_ids=group_ids,
            enforce_groups=enforce_groups,
        )
        if inspect.isawaitable(result):
            return await result
        if isinstance(result, list):
            return result

        if owner_tenant_id == viewer_tenant_id:
            return candidate_document_ids or []

        logger.warning(
            "DocumentRepository visibility getter returned non-awaitable unsupported value; denying shared vector scope owner=%s viewer=%s",
            owner_tenant_id,
            viewer_tenant_id,
        )
        return []

    async def _list_non_ready_document_ids_with_chunks(
        self, tenant_id: str
    ) -> list[str] | None:
        """Resolve the retrieval-time blocklist of non-READY documents with chunks.

        This is a data-quality filter, not an authorization decision: it must be
        resolved for every target regardless of ACL/group settings (unlike
        `_list_visible_document_ids`, which stays purely ACL semantics - see
        graph_traversal_guard.py and the Part A spec notes). Degrades gracefully
        (no exclusion) if the repository does not implement the method, mirroring
        the fallback pattern used by `_list_visible_document_ids`.
        """
        getter = getattr(self.document_repository, "list_non_ready_document_ids_with_chunks", None)
        if not callable(getter):
            return None

        try:
            result = getter(tenant_id=tenant_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            logger.warning(
                "Failed to resolve non-READY document blocklist for tenant=%s: %s",
                tenant_id,
                e,
            )
            return None

        if isinstance(result, list):
            return result
        return None

    async def _resolve_vector_targets(
        self,
        viewer_tenant_id: str,
        query_scopes: QueryScopes,
        candidate_document_ids: list[str] | None,
        include_trace: bool = False,
        trace: list[dict[str, Any]] | None = None,
    ) -> list[VectorSearchTarget]:
        """Resolve the vector collections and document ACL filters for the current query."""
        targets: list[VectorSearchTarget] = []
        target_trace: list[dict[str, Any]] = []

        for scope_tenant_id in query_scopes.vector_scopes:
            if scope_tenant_id != viewer_tenant_id and not _get_settings().enable_acl_aware_vector_retrieval:
                target_trace.append(
                    {
                        "tenant_id": scope_tenant_id,
                        "collection": None,
                        "document_ids_count": None,
                        "requested_document_ids_count": len(candidate_document_ids) if candidate_document_ids is not None else None,
                        "acl_filtered_out_count": None,
                        "skipped": True,
                        "reason": "shared_vector_retrieval_disabled",
                    }
                )
                continue

            scope_document_ids: list[str] | None = None

            if candidate_document_ids is not None:
                scope_document_ids = await self._list_visible_document_ids(
                    viewer_tenant_id=viewer_tenant_id,
                    owner_tenant_id=scope_tenant_id,
                    candidate_document_ids=candidate_document_ids,
                    group_ids=list(query_scopes.group_ids),
                    enforce_groups=query_scopes.enforce_groups,
                )
                if not scope_document_ids:
                    continue
            elif scope_tenant_id != viewer_tenant_id or query_scopes.enforce_groups:
                # Fail closed: without an incoming candidate set we must STILL resolve
                # the group-visible allowlist for the viewer's own tenant when group
                # enforcement is on — otherwise Milvus (tenant-filter only, no group
                # ACL) returns every chunk in the tenant, leaking documents the user's
                # groups were never granted. Shared tenants are always ACL-resolved.
                scope_document_ids = await self._list_visible_document_ids(
                    viewer_tenant_id=viewer_tenant_id,
                    owner_tenant_id=scope_tenant_id,
                    candidate_document_ids=None,
                    group_ids=list(query_scopes.group_ids),
                    enforce_groups=query_scopes.enforce_groups,
                )
                if not scope_document_ids:
                    continue

            collection_name = await self._resolve_active_collection(scope_tenant_id)
            exclude_document_ids = await self._list_non_ready_document_ids_with_chunks(
                scope_tenant_id
            )
            targets.append(
                VectorSearchTarget(
                    tenant_id=scope_tenant_id,
                    collection_name=collection_name,
                    document_ids=scope_document_ids,
                    exclude_document_ids=exclude_document_ids,
                )
            )
            requested_document_ids_count = len(candidate_document_ids) if candidate_document_ids is not None else None
            acl_filtered_out_count = None
            if requested_document_ids_count is not None and scope_document_ids is not None:
                acl_filtered_out_count = max(requested_document_ids_count - len(scope_document_ids), 0)

            target_trace.append(
                {
                    "tenant_id": scope_tenant_id,
                    "collection": collection_name,
                    "document_ids_count": len(scope_document_ids) if scope_document_ids is not None else None,
                    "requested_document_ids_count": requested_document_ids_count,
                    "acl_filtered_out_count": acl_filtered_out_count,
                }
            )

        if include_trace and trace is not None:
            trace.append({"step": "resolve_vector_targets", "targets": target_trace})

        return targets

    async def _search_vector_targets(
        self,
        query_vector: list[float],
        vector_targets: list[VectorSearchTarget],
        limit: int,
        filters: dict[str, Any],
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Search all resolved vector targets and merge the results."""
        merged_results: list[Any] = []
        target_trace: list[dict[str, Any]] = []

        for target in vector_targets:
            logger.debug(
                "Searching vector store collection=%s owner_tenant=%s allowed_docs=%s",
                target.collection_name,
                target.tenant_id,
                len(target.document_ids) if target.document_ids is not None else "all",
            )

            target_results = await self.vector_searcher.search(
                query_vector=query_vector,
                tenant_id=target.tenant_id,
                document_ids=target.document_ids,
                limit=limit * 3,
                score_threshold=self.config.score_threshold,
                filters=filters,
                collection_name=target.collection_name,
                exclude_document_ids=target.exclude_document_ids,
            )
            merged_results.extend(target_results)
            target_trace.append(
                {
                    "tenant_id": target.tenant_id,
                    "collection": target.collection_name,
                    "document_ids_count": len(target.document_ids) if target.document_ids is not None else None,
                    "results_count": len(target_results),
                }
            )

        merged_results.sort(key=lambda candidate: candidate.score, reverse=True)
        visible_results = await self._filter_unpublished_generation_results(merged_results)
        return visible_results[:limit], target_trace

    async def _filter_unpublished_generation_results(self, results: list[Any]) -> list[Any]:
        """Keep only chunks visible through each document's published generation."""
        if not results:
            return results

        def result_generation_id(result: Any) -> str | None:
            generation_id = getattr(result, "generation_id", None)
            metadata = getattr(result, "metadata", None) or {}
            return generation_id if generation_id is not None else metadata.get("generation_id")

        # Always validate: legacy (NULL-generation) hits of a republished document
        # are hidden by get_chunks, even when no hit in the batch has a generation.
        get_chunks = getattr(self.document_repository, "get_chunks", None)
        if not callable(get_chunks):
            return [result for result in results if result_generation_id(result) is None]

        try:
            visible_chunks = await get_chunks([result.chunk_id for result in results])
        except Exception as exc:
            logger.warning("Could not validate vector result generations: %s", exc)
            return [result for result in results if result_generation_id(result) is None]

        visible_generations = {
            chunk.id: getattr(chunk, "generation_id", None) for chunk in visible_chunks
        }

        return [
            result
            for result in results
            if result.chunk_id in visible_generations
            and result_generation_id(result) == visible_generations[result.chunk_id]
        ]


    async def _search_vector_targets_hybrid(
        self,
        query_vector: list[float],
        sparse_vector: dict[int, float],
        vector_targets: list[VectorSearchTarget],
        limit: int,
        filters: dict[str, Any],
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Search all resolved vector targets using hybrid search and merge the results."""
        merged_results: list[Any] = []
        target_trace: list[dict[str, Any]] = []

        for target in vector_targets:
            logger.debug(
                "Hybrid searching vector store collection=%s owner_tenant=%s allowed_docs=%s",
                target.collection_name,
                target.tenant_id,
                len(target.document_ids) if target.document_ids is not None else "all",
            )

            # NOTE: self.config.score_threshold is calibrated for dense cosine
            # similarity (0-1). Hybrid search's fused score is on a different scale
            # (Milvus RRF/weighted rerank output, ~0.01-0.03), so that cosine
            # threshold must NOT be forwarded here as-is - it would silently drop
            # every hybrid result. Leave score_threshold unset (None) until a
            # separately-calibrated hybrid threshold exists.
            target_results = await self.vector_searcher.hybrid_search(
                query_vector=query_vector,
                sparse_vector=sparse_vector,
                tenant_id=target.tenant_id,
                document_ids=target.document_ids,
                limit=limit * 3,
                filters=filters,
                collection_name=target.collection_name,
                exclude_document_ids=target.exclude_document_ids,
            )
            merged_results.extend(target_results)
            target_trace.append(
                {
                    "tenant_id": target.tenant_id,
                    "collection": target.collection_name,
                    "document_ids_count": len(target.document_ids) if target.document_ids is not None else None,
                    "results_count": len(target_results),
                    "mode": "hybrid",
                }
            )

        merged_results.sort(key=lambda candidate: candidate.score, reverse=True)
        visible_results = await self._filter_unpublished_generation_results(merged_results)
        return visible_results[:limit], target_trace

    async def _resolve_graph_targets(
        self,
        viewer_tenant_id: str,
        query_scopes: QueryScopes,
        candidate_document_ids: list[str] | None,
        include_trace: bool = False,
        trace: list[dict[str, Any]] | None = None,
    ) -> list[GraphSearchTarget]:
        """Resolve the graph scopes and document ACL filters for the current query."""
        targets: list[GraphSearchTarget] = []
        target_trace: list[dict[str, Any]] = []

        for scope_tenant_id in query_scopes.graph_scopes:
            if scope_tenant_id != viewer_tenant_id and not _get_settings().enable_acl_aware_graph_retrieval:
                target_trace.append(
                    {
                        "tenant_id": scope_tenant_id,
                        "document_ids_count": None,
                        "requested_document_ids_count": len(candidate_document_ids) if candidate_document_ids is not None else None,
                        "acl_filtered_out_count": None,
                        "skipped": True,
                        "reason": "shared_graph_retrieval_disabled",
                    }
                )
                continue

            allowed_doc_ids: list[str] | None = None

            if candidate_document_ids is not None:
                allowed_doc_ids = await self._list_visible_document_ids(
                    viewer_tenant_id=viewer_tenant_id,
                    owner_tenant_id=scope_tenant_id,
                    candidate_document_ids=candidate_document_ids,
                    group_ids=list(query_scopes.group_ids),
                    enforce_groups=query_scopes.enforce_groups,
                )
                if not allowed_doc_ids:
                    continue
            elif scope_tenant_id != viewer_tenant_id or query_scopes.enforce_groups:
                # Fail closed: mirror the vector path — resolve the group-visible
                # allowlist for the viewer's own tenant when group enforcement is on,
                # even without an incoming candidate set, so graph retrieval cannot
                # surface documents the user's groups were never granted.
                allowed_doc_ids = await self._list_visible_document_ids(
                    viewer_tenant_id=viewer_tenant_id,
                    owner_tenant_id=scope_tenant_id,
                    candidate_document_ids=None,
                    group_ids=list(query_scopes.group_ids),
                    enforce_groups=query_scopes.enforce_groups,
                )
                if not allowed_doc_ids:
                    continue

            excluded_doc_ids = await self._list_non_ready_document_ids_with_chunks(
                scope_tenant_id
            )
            targets.append(
                GraphSearchTarget(
                    tenant_id=scope_tenant_id,
                    allowed_doc_ids=allowed_doc_ids,
                    excluded_doc_ids=excluded_doc_ids,
                )
            )
            requested_document_ids_count = len(candidate_document_ids) if candidate_document_ids is not None else None
            acl_filtered_out_count = None
            if requested_document_ids_count is not None and allowed_doc_ids is not None:
                acl_filtered_out_count = max(requested_document_ids_count - len(allowed_doc_ids), 0)

            target_trace.append(
                {
                    "tenant_id": scope_tenant_id,
                    "document_ids_count": len(allowed_doc_ids) if allowed_doc_ids is not None else None,
                    "requested_document_ids_count": requested_document_ids_count,
                    "acl_filtered_out_count": acl_filtered_out_count,
                }
            )

        if include_trace and trace is not None:
            trace.append({"step": "resolve_graph_targets", "targets": target_trace})

        return targets

    async def _execute_global_search(
        self,
        query_text: str,
        viewer_tenant_id: str,
        graph_targets: list[GraphSearchTarget],
        tenant_config: dict[str, Any] | None,
        trace: list[dict[str, Any]],
    ) -> RetrievalResult:
        """Execute ACL-aware global search across graph scopes."""
        merged_candidates: list[dict[str, Any]] = []
        seen_candidate_ids: set[str] = set()
        target_trace: list[dict[str, Any]] = []

        for target in graph_targets:
            result = await self.global_search.search(
                query=query_text,
                tenant_id=target.tenant_id,
                tenant_config=tenant_config,
                allowed_doc_ids=target.allowed_doc_ids,
            )
            candidates = result.get("candidates", [])
            target_trace.append(
                {
                    "tenant_id": target.tenant_id,
                    "document_ids_count": len(target.allowed_doc_ids) if target.allowed_doc_ids is not None else None,
                    "results_count": len(candidates),
                }
            )

            for candidate in candidates:
                candidate_id = candidate.get("chunk_id") or f"{candidate.get('document_id')}::{candidate.get('content')}"
                if candidate_id in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(candidate_id)
                merged_candidates.append(candidate)

        merged_candidates.sort(key=lambda item: float(item.get("score", 0) or 0), reverse=True)
        trace.append(
            {
                "step": "global_search",
                "targets": target_trace,
                "sources": [candidate.get("chunk_id") for candidate in merged_candidates if candidate.get("chunk_id")],
            }
        )

        return RetrievalResult(
            chunks=merged_candidates,
            query=query_text,
            tenant_id=viewer_tenant_id,
            latency_ms=0,
            trace=trace,
        )

    def _resolve_embedding_service(self, tenant_config: dict[str, Any] | None) -> EmbeddingService:
        """Resolve embedding service based on tenant config."""
        if not tenant_config:
            return self.embedding_service

        # Check if tenant overrides critical embedding settings
        t_provider = tenant_config.get("embedding_provider")
        t_model = tenant_config.get("embedding_model")
        t_ollama_url = tenant_config.get("ollama_base_url")
        t_dimensions: int | None = tenant_config.get("embedding_dimensions")

        # If no overrides, return default
        if not (t_provider or t_model or t_ollama_url or t_dimensions):
            return self.embedding_service

        # Build scoped factory
        from src.core.generation.domain.ports.provider_factory import build_provider_factory
        from src.shared.kernel.runtime import get_settings
        from src.shared.model_registry import embedding_supports_dimensions

        settings = get_settings()

        # Valid Ollama URL?
        effective_ollama_url = t_ollama_url or settings.ollama_base_url

        factory = build_provider_factory(
            openai_api_key=settings.openai_api_key,
            anthropic_api_key=settings.anthropic_api_key,
            ollama_base_url=effective_ollama_url,
        )

        # Determine provider name
        # If tenant doesn't specify provider but specifies model, we might need to resolve it.
        # If tenant specifies nothing, we shouldn't be here (checked above).

        # If t_provider is None, use default? Or resolve from model?
        # Safe default: if ollama_url is set, likely want ollama? Not necessarily.

        provider_name = t_provider or self.config.default_embedding_provider
        effective_model = t_model or self.config.default_embedding_model

        # Enforce supports_dimensions: reject reduced-dim requests on models that don't
        # support it. Requesting the model's native dimension is not a reduction.
        if t_dimensions and effective_model:
            from src.shared.model_registry import embedding_native_dimensions

            native_dims = embedding_native_dimensions(effective_model, provider=provider_name)
            if t_dimensions != native_dims and not embedding_supports_dimensions(
                effective_model, provider=provider_name
            ):
                raise ValueError(
                    f"Embedding model '{effective_model}' (provider '{provider_name}') does not "
                    f"support dimension reduction. Cannot use embedding_dimensions={t_dimensions}. "
                    "Remove embedding_dimensions from the tenant config or switch to a model "
                    "that supports Matryoshka dimension reduction (e.g. text-embedding-3-small)."
                )

        return EmbeddingService(
            provider=factory.get_embedding_provider(
                provider_name=provider_name,
                model=effective_model,
            ),
            model=effective_model,
            dimensions=t_dimensions,
        )

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
        global_rules: list[str] | None = None,
        memory_context: str | None = None,
        query_scopes: QueryScopes | None = None,
        for_generation: bool = False,
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
        logger.debug("Retrieval started for tenant=%s query=%s", tenant_id, query[:120])
        trace = []
        top_k = top_k or self.config.top_k
        options = options or QueryOptions()
        if query_scopes is None:
            initial_tenant_id = str(tenant_id or "default")
            tenant_config = await self._get_effective_tenant_config(initial_tenant_id)
            groups_enforced = bool((tenant_config or {}).get("groups_enforced", False))
            resolved_scopes = resolve_query_scopes(initial_tenant_id, enforce_groups=groups_enforced)
        else:
            resolved_scopes = query_scopes
            tenant_config = await self._get_effective_tenant_config(resolved_scopes.effective_tenant_id)
        resolved_tenant_id = resolved_scopes.effective_tenant_id
        if include_trace:
            trace.append(
                {
                    "step": "resolve_query_scopes",
                    "effective_tenant_id": resolved_scopes.effective_tenant_id,
                    "vector_scopes": resolved_scopes.vector_scopes,
                    "graph_scopes": resolved_scopes.graph_scopes,
                    "enforce_groups": resolved_scopes.enforce_groups,
                }
            )

        raw_document_ids = QueryParser.parse(query).document_ids or []
        has_document_scope = document_ids is not None or bool(raw_document_ids)
        requested_document_ids = (
            set(document_ids).intersection(raw_document_ids)
            if document_ids is not None and raw_document_ids
            else set(document_ids if document_ids is not None else raw_document_ids)
        )
        if has_document_scope and not requested_document_ids:
            return RetrievalResult(
                chunks=[],
                query=query,
                tenant_id=resolved_tenant_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                search_mode=SearchMode.BASIC.value,
                trace=trace,
            )

        # Step 1: Contextual Rewriting
        processed_query = query
        # Rewrite if history is provided OR explicit system constraints (rules/memory) are given
        if options.use_rewrite and (history or global_rules or memory_context):
            processed_query = await self.rewriter.rewrite(
                query,
                history=history,
                global_rules=global_rules,
                memory_context=memory_context,
                tenant_config=tenant_config,
            )

        structured_query = QueryParser.parse(processed_query)

        # Merge filters
        all_document_ids = sorted(requested_document_ids)
        if for_generation:
            # Apply ACLs and the source policy before taxonomy can broaden selection.
            visible_ids = set()
            for owner_id in resolved_scopes.vector_scopes:
                visible_ids.update(await self._list_visible_document_ids(
                    viewer_tenant_id=resolved_tenant_id,
                    owner_tenant_id=owner_id,
                    candidate_document_ids=all_document_ids or None,
                    group_ids=list(resolved_scopes.group_ids),
                    enforce_groups=resolved_scopes.enforce_groups,
                ))
            editions = await self.document_repository.get_editions_by_ids(list(visible_ids))
            all_document_ids = sorted(
                doc_id for doc_id in visible_ids if editions.get(doc_id) == "commercial"
            )
            if not all_document_ids:
                return RetrievalResult(
                    chunks=[], query=query, tenant_id=resolved_tenant_id,
                    latency_ms=(time.perf_counter() - start_time) * 1000,
                    search_mode=SearchMode.BASIC.value, trace=trace,
                )
        all_filters = {**(filters or {})}
        if all_filters.get("tags") is None and structured_query.tags:
            all_filters["tags"] = structured_query.tags
        # Date range filters could be added here

        # Taxonomy Routing: resolve edition/audience context and pre-filter document IDs
        # Explicit filter overrides take precedence over query-inferred context.
        _explicit_edition = all_filters.pop("edition", None)
        _explicit_audience = all_filters.pop("audience", None)
        _explicit_source_family = all_filters.pop("source_family", None)

        # Taxonomy inference must use the ORIGINAL user query, never the LLM-rewritten
        # one: the rewriter can inject edition-determining keywords (e.g. "CE") that
        # would misroute the taxonomy filter. Parse the raw query for a clean signal.
        _tax_ctx = resolve_product_context(QueryParser.parse(query).cleaned_query)
        # Prefer the full edition set when the query references both editions
        # (dual mention). Falls back to the single scalar edition otherwise.
        _inferred_edition = _tax_ctx.editions or (
            _tax_ctx.edition if _tax_ctx.edition != "unknown" else None
        )
        _tax_edition = (
            _explicit_edition if _explicit_edition is not None else _inferred_edition
        )
        _tax_audience = _explicit_audience
        _tax_source_family = _explicit_source_family
        _taxonomy_filter_explicit = any(
            value is not None
            for value in (_explicit_edition, _explicit_audience, _explicit_source_family)
        )

        _taxonomy_doc_ids: list[str] | None = None
        _broadening_stage = "none"

        _has_taxonomy_signal = _taxonomy_filter_explicit or bool(
            _tax_edition or _tax_audience or _tax_source_family
        )
        if _has_taxonomy_signal and hasattr(self.document_repository, "list_visible_document_ids_by_taxonomy"):
            _strict_ids = []
            for owner_id in resolved_scopes.vector_scopes:
                _owner_ids = await self.document_repository.list_visible_document_ids_by_taxonomy(
                    viewer_tenant_id=resolved_tenant_id,
                    owner_tenant_id=owner_id,
                    candidate_document_ids=all_document_ids or None,
                    edition=_tax_edition,
                    audience=_tax_audience,
                    source_family=_tax_source_family,
                )
                _strict_ids.extend(_owner_ids or [])
            _strict_ids = list(dict.fromkeys(_strict_ids))

            if _strict_ids:
                _taxonomy_doc_ids = _strict_ids
                _broadening_stage = "strict"
            elif _taxonomy_filter_explicit:
                _taxonomy_doc_ids = []
                _broadening_stage = "strict_empty"
            else:
                _broadening_stage = "unfiltered"

            if include_trace:
                trace.append({
                    "step": "taxonomy_routing",
                    "inferred_edition": _tax_ctx.edition,
                    "inferred_audience": _tax_ctx.audience,
                    "explicit_edition": _explicit_edition,
                    "explicit_audience": _explicit_audience,
                    "audience_filter": _tax_audience,
                    "confidence": _tax_ctx.confidence,
                    "broadening_stage": _broadening_stage,
                    "strict_candidate_count": len(_strict_ids) if _has_taxonomy_signal else None,
                    "taxonomy_doc_ids_count": len(_taxonomy_doc_ids) if _taxonomy_doc_ids else 0,
                })

        taxonomy_strict_empty = _taxonomy_doc_ids is not None and not _taxonomy_doc_ids
        if _taxonomy_doc_ids is not None:
            all_document_ids = _taxonomy_doc_ids

        article_reference = _extract_article_reference(query)
        if article_reference:
            candidate_ids: set[str] = set()
            if not taxonomy_strict_empty:
                for owner_id in resolved_scopes.vector_scopes:
                    candidate_ids.update(await self._list_visible_document_ids(
                        viewer_tenant_id=resolved_tenant_id,
                        owner_tenant_id=owner_id,
                        candidate_document_ids=all_document_ids or None,
                        group_ids=list(resolved_scopes.group_ids),
                        enforce_groups=resolved_scopes.enforce_groups,
                    ))

            lookup = getattr(self.document_repository, "find_document_ids_by_reference_number", None)
            matches: set[str] = set()
            reference_status = "not_found"
            if not callable(lookup):
                reference_status = "unavailable"
            elif candidate_ids:
                try:
                    lookup_result = lookup(
                        article_reference,
                        candidate_document_ids=sorted(candidate_ids),
                    )
                    if inspect.isawaitable(lookup_result):
                        lookup_result = await lookup_result
                    if isinstance(lookup_result, list):
                        matches = candidate_ids.intersection(lookup_result)
                        reference_status = "found" if matches else "not_found"
                    else:
                        reference_status = "unavailable"
                except Exception as e:
                    logger.warning("Article reference lookup failed: %s", e)
                    reference_status = "error"

            if matches:
                all_document_ids = sorted(matches)
            if include_trace:
                trace.append({
                    "step": "article_reference",
                    "reference_number": article_reference,
                    "status": reference_status,
                    "matched_document_count": len(matches),
                })

        if taxonomy_strict_empty:
            return RetrievalResult(
                chunks=[],
                query=query,
                tenant_id=resolved_tenant_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                search_mode=SearchMode.BASIC.value,
                trace=trace,
            )

        # Step 3: Query Routing
        _router_start = time.perf_counter()
        search_mode = await self.router.route(
            structured_query.cleaned_query,
            explicit_mode=SearchMode.BASIC if for_generation else options.search_mode,
            tenant_config=tenant_config,
        )
        _router_latency_ms = (time.perf_counter() - _router_start) * 1000
        if for_generation:
            # Graph summaries lack reliable per-document edition provenance.
            search_mode = SearchMode.BASIC
        effective_search_mode = search_mode

        # SECURITY: STRUCTURED runs tenant-scoped Cypher with NO group ACL (Neo4j
        # has no Postgres-RLS backstop), and options.search_mode is a public request
        # field the router honours verbatim — so a caller can ask for it explicitly.
        # Under group enforcement the mode is refused here and the query falls
        # through to the ACL-enforced vector path below. Guarding at this single
        # point covers every caller of retrieve(): stream, non-stream, agent tool
        # and drift.
        _structured_allowed = not getattr(resolved_scopes, "enforce_groups", False)
        if not _structured_allowed and search_mode == SearchMode.STRUCTURED:
            effective_search_mode = SearchMode.BASIC
            logger.info(
                "STRUCTURED mode requested but group enforcement is active for tenant=%s; "
                "falling back to ACL-enforced vector search",
                resolved_tenant_id,
            )

        vector_targets: list[VectorSearchTarget] = []
        graph_targets: list[GraphSearchTarget] = []

        # Step 4 & 5: Search Execution based on Mode

        try:
            if search_mode == SearchMode.GLOBAL:
                graph_targets = await self._resolve_graph_targets(
                    viewer_tenant_id=resolved_tenant_id,
                    query_scopes=resolved_scopes,
                    candidate_document_ids=all_document_ids or None,
                    include_trace=include_trace,
                    trace=trace,
                )
                result = await self._execute_global_search(
                    query_text=structured_query.cleaned_query,
                    viewer_tenant_id=resolved_tenant_id,
                    graph_targets=graph_targets,
                    tenant_config=tenant_config,
                    trace=trace,
                )
            elif search_mode == SearchMode.DRIFT:
                res = await self.drift_search.search(
                    query=structured_query.cleaned_query,
                    tenant_id=resolved_tenant_id,
                    tenant_config=tenant_config,
                    query_scopes=resolved_scopes,
                    document_ids=all_document_ids or None,
                    filters={**(filters or {}), **all_filters},
                    options=options,
                    for_generation=for_generation,
                    include_trace=include_trace,
                )
                if include_trace:
                    trace.extend(res["trace"])
                result = RetrievalResult(
                    chunks=res["candidates"],
                    query=query,
                    tenant_id=resolved_tenant_id,
                    latency_ms=0,
                    trace=res["trace"],
                    reranking_ms=res["reranking_ms"],
                )
            elif search_mode == SearchMode.STRUCTURED and _structured_allowed:
                from src.core.retrieval.application.query.structured_query import (
                    structured_executor,
                )

                structured_result = await structured_executor.try_execute(
                    query=structured_query.cleaned_query,
                    tenant_id=resolved_tenant_id,
                )
                if structured_result and structured_result.success:
                    # Wrap tabular data as chunk-like dicts so the caller gets a
                    # consistent RetrievalResult regardless of mode.
                    chunks = [
                        {"chunk_id": f"structured:{i}", "score": 1.0, "content": str(row), **row}
                        for i, row in enumerate(structured_result.data)
                    ]
                    result = RetrievalResult(
                        chunks=chunks,
                        query=query,
                        tenant_id=resolved_tenant_id,
                        latency_ms=0,
                    )
                else:
                    # Executor failed (e.g. graph client unavailable); fall back to vector search
                    effective_search_mode = SearchMode.BASIC
                    logger.warning(
                        "STRUCTURED query execution failed for tenant=%s; falling back to vector search",
                        resolved_tenant_id,
                    )
                    vector_targets = await self._resolve_vector_targets(
                        viewer_tenant_id=resolved_tenant_id,
                        query_scopes=resolved_scopes,
                        candidate_document_ids=all_document_ids or None,
                        include_trace=include_trace,
                        trace=trace,
                    )
                    result = await self._execute_vector_search(
                        structured_query=structured_query,
                        tenant_id=resolved_tenant_id,
                        document_ids=all_document_ids,
                        filters=all_filters,
                        top_k=top_k,
                        options=options,
                        trace=trace,
                        vector_targets=vector_targets,
                        tenant_config=tenant_config,
                        include_trace=include_trace,
                    )
            else:
                vector_targets = await self._resolve_vector_targets(
                    viewer_tenant_id=resolved_tenant_id,
                    query_scopes=resolved_scopes,
                    candidate_document_ids=all_document_ids or None,
                    include_trace=include_trace,
                    trace=trace,
                )
                # LOCAL mode requires entity_embeddings Milvus collection (not yet created).
                # TODO: Create entity_embeddings collection — see ARCHITECTURE_AUDIT.md §4.3
                # Until then, LOCAL falls back to BASIC vector search.
                if search_mode == SearchMode.LOCAL:
                    effective_search_mode = SearchMode.BASIC
                    logger.warning(
                        "SearchMode.LOCAL requested but entity_embeddings collection does not exist; "
                        "falling back to BASIC vector search. tenant=%s", resolved_tenant_id
                    )
                result = await self._execute_vector_search(
                    structured_query=structured_query,
                    tenant_id=resolved_tenant_id,
                    document_ids=all_document_ids,
                    filters=all_filters,
                    top_k=top_k,
                    options=options,
                    trace=trace,
                    vector_targets=vector_targets,
                    tenant_config=tenant_config,
                    include_trace=include_trace,
                )
        except Exception as e:
            logger.error(f"Retrieval failed for mode {search_mode}: {e}")
            effective_search_mode = SearchMode.BASIC
            # Fallback to simple vector search
            if not vector_targets:
                vector_targets = await self._resolve_vector_targets(
                    viewer_tenant_id=resolved_tenant_id,
                    query_scopes=resolved_scopes,
                    candidate_document_ids=all_document_ids or None,
                    include_trace=include_trace,
                    trace=trace,
                )
            result = await self._execute_vector_search(
                structured_query=structured_query,
                tenant_id=resolved_tenant_id,
                document_ids=all_document_ids,
                filters=all_filters,
                top_k=top_k,
                options=options,
                trace=trace,
                vector_targets=vector_targets,
                include_trace=include_trace,
            )

        if for_generation:
            # Recheck cached/backend results before any sufficiency LLM sees them.
            allowed_ids = set(all_document_ids)
            result.chunks = [
                c for c in result.chunks
                if (c.get("document_id") if isinstance(c, dict) else c.document_id) in allowed_ids
            ]

        # Step 9: Sufficient-context gate + iterative retrieval.
        # Only meaningful for vector-based modes (GLOBAL/DRIFT do their own
        # iteration; STRUCTURED returns tabular rows). Gated by option, off by
        # default — unknown judgments stop additional retrieval without blocking
        # the response or claiming the context is sufficient.
        if (
            options.use_sufficiency_loop
            and options.max_sufficiency_rounds > 0
            and vector_targets
        ):
            await self._run_sufficiency_loop(
                result=result,
                processed_query=processed_query,
                tenant_id=resolved_tenant_id,
                document_ids=all_document_ids,
                filters=all_filters,
                top_k=top_k,
                options=options,
                trace=trace,
                vector_targets=vector_targets,
                tenant_config=tenant_config,
                include_trace=include_trace,
            )

        if for_generation:
            result.chunks = [
                c for c in result.chunks
                if (c.get("document_id") if isinstance(c, dict) else c.document_id) in allowed_ids
            ]
            result.chunks = await self._append_document_continuations(
                result.chunks,
                allowed_ids=allowed_ids,
                trace=trace if include_trace else None,
            )

        # Record latency for circuit breaker
        total_latency = (time.perf_counter() - start_time) * 1000
        self.circuit_breaker.record_latency(total_latency)

        result.latency_ms = total_latency
        result.search_mode = effective_search_mode.value
        result.router_latency_ms = _router_latency_ms
        if not include_trace:
            result.trace = []
        else:
            result.trace = trace

        return result

    async def _append_document_continuations(
        self,
        chunks: list[Any],
        *,
        allowed_ids: set[str],
        trace: list[dict[str, Any]] | None = None,
    ) -> list[Any]:
        """Keep split sections together in the generation context.

        A document that already supplied two or more final chunks, and every
        sufficiency gap hit, also supplies the chunk that follows (e.g. symptom/cause
        chunk -> solution chunk), inserted right after its predecessor. The two
        kinds have separate caps. Lookup failures leave the list unchanged.
        Generation results can therefore exceed ``top_k`` by the sufficiency additions
        (up to rounds x SUFFICIENCY_GAP_HITS_PER_ROUND) plus up to
        MAX_DOCUMENT_CONTINUATIONS + MAX_GAP_CONTINUATIONS continuations; chunk-count
        metrics and evaluation contexts include them (``source="document_continuation"``).
        """
        if not chunks or not all(isinstance(c, dict) for c in chunks):
            return chunks
        fetch = getattr(self.document_repository, "get_next_chunks", None)
        per_document = Counter(c.get("document_id") for c in chunks)

        def is_gap_parent(chunk: dict[str, Any]) -> bool:
            return bool(chunk.get("sufficiency_gap_hit"))

        parent_ids = [
            c["chunk_id"]
            for c in chunks
            if c.get("chunk_id")
            and (is_gap_parent(c) or per_document[c.get("document_id")] >= 2)
        ]
        if fetch is None or not parent_ids:
            return chunks
        try:
            following = await fetch(parent_ids)
        except Exception as e:
            logger.warning(f"Document continuation lookup failed: {e}")
            return chunks
        if not isinstance(following, dict):
            return chunks

        selected = {c.get("chunk_id") for c in chunks}
        expanded: list[Any] = []
        added: list[dict[str, Any]] = []
        used = {True: 0, False: 0}  # continuations per parent kind (gap hit or not)
        caps = {True: MAX_GAP_CONTINUATIONS, False: MAX_DOCUMENT_CONTINUATIONS}
        for chunk in chunks:
            expanded.append(chunk)
            nxt = following.get(chunk.get("chunk_id"))
            gap_parent = is_gap_parent(chunk)
            if (
                nxt is None
                or used[gap_parent] >= caps[gap_parent]
                or nxt.id in selected
                or nxt.document_id != chunk.get("document_id")
                or nxt.document_id not in allowed_ids
            ):
                continue
            expanded.append(
                {
                    "chunk_id": nxt.id,
                    "document_id": nxt.document_id,
                    "content": nxt.content,
                    "metadata": nxt.metadata_,
                    "score": chunk.get("score"),
                    "score_type": chunk.get("score_type"),
                    "source": "document_continuation",
                }
            )
            selected.add(nxt.id)
            used[gap_parent] += 1
            added.append({"chunk_id": nxt.id, "after": chunk.get("chunk_id"), "gap_hit": gap_parent})
        if trace is not None and added:
            trace.append({"step": "document_continuations", "added": added})
        return expanded

    async def _merge_candidate_groups(
        self,
        groups: list[list[dict[str, Any]]],
        *,
        query: str,
        top_k: int,
        provider_timings: dict[str, float] | None = None,
        rerank: bool = True,
    ) -> tuple[list[dict[str, Any]], float, bool]:
        """Merge ordered query result groups, reranking on one shared query.

        With ``rerank=False`` the additive policy is used directly: base group
        order first, then one candidate at a time from each later group.
        """
        unique_groups: list[list[dict[str, Any]]] = []
        seen_chunk_ids: set[Any] = set()
        seen_doc_content: set[tuple[Any, str]] = set()
        for group in groups:
            unique_group = []
            for candidate in group:
                chunk_id = candidate.get("chunk_id")
                document_id = candidate.get("document_id")
                content = candidate.get("content")
                if chunk_id and chunk_id in seen_chunk_ids:
                    continue
                if chunk_id:
                    seen_chunk_ids.add(chunk_id)
                if document_id and isinstance(content, str) and content:
                    content_key = (document_id, content)
                    if content_key in seen_doc_content:
                        continue
                    seen_doc_content.add(content_key)
                unique_group.append(dict(candidate))
            unique_groups.append(unique_group)

        union = [candidate for group in unique_groups for candidate in group]
        reranking_ms = 0.0
        if rerank and self.reranker is not None and union:
            started = time.perf_counter()
            try:
                response = await self.reranker.rerank(
                    query=query,
                    documents=[str(candidate.get("content") or "") for candidate in union],
                    top_k=top_k,
                )
                if provider_timings is not None:
                    provider_timings.update(_provider_rerank_timings(response))
                validated = _validated_rerank_results(
                    response.results, input_count=len(union), top_k=top_k
                )
                if validated is None:
                    raise ValueError("malformed or incomplete reranker results")
                ranked = []
                for index, score in validated:
                    candidate = dict(union[index])
                    candidate["score"] = score
                    candidate["score_type"] = "reranker"
                    ranked.append(candidate)
                reranking_ms = (time.perf_counter() - started) * 1000
                floor = self.config.rerank_score_floor
                if floor is not None:
                    ranked = [c for c in ranked if c["score"] >= floor]
                return ranked[:top_k], reranking_ms, True
            except Exception as e:
                reranking_ms = (time.perf_counter() - started) * 1000
                logger.warning("Common-query reranking failed; preserving group order: %s", e)

        # Scores from different queries are not comparable. Preserve the base
        # order, then fairly take one candidate at a time from each gap group.
        fallback = list(unique_groups[0]) if unique_groups else []
        gap_groups = unique_groups[1:]
        round_idx = 0
        while len(fallback) < top_k and any(round_idx < len(group) for group in gap_groups):
            for group in gap_groups:
                if round_idx < len(group) and len(fallback) < top_k:
                    fallback.append(group[round_idx])
            round_idx += 1
        return fallback[:top_k], reranking_ms, False

    async def _run_sufficiency_loop(
        self,
        *,
        result: RetrievalResult,
        processed_query: str,
        tenant_id: str,
        document_ids: list[str] | None,
        filters: dict[str, Any],
        top_k: int,
        options: QueryOptions,
        trace: list[dict],
        vector_targets: list[VectorSearchTarget],
        tenant_config: dict[str, Any] | None,
        include_trace: bool,
    ) -> None:
        """
        Iterative retrieval gate (Sufficient Context Agent pattern).

        Judges whether `result.chunks` are sufficient to answer `processed_query`.
        While insufficient and rounds remain, runs the proposed gap queries
        through vector search and ADDS their hits to `result.chunks` in place:
        the current context keeps its order, and each round appends up to SUFFICIENCY_GAP_HITS_PER_ROUND new
        chunks taken one at a time from each gap group in that group's own rank
        order (never re-scored against the original query, which is what judged
        the context insufficient). Gap hits reranked below SUFFICIENCY_GAP_MIN_SCORE
        are not admitted. Total length is capped by the budget.
        """
        # Decomposition off for gap queries to avoid combinatorial fan-out.
        gap_options = options.model_copy(update={"use_decomposition": False})
        # Context budget: gap chunks are ADDED (the loop fills gaps), not capped
        # back to top_k — otherwise narrow gap chunks evict the original best
        # chunks and the loop hurts more than it helps.
        budget = options.sufficiency_max_chunks or (
            top_k + options.max_sufficiency_rounds * SUFFICIENCY_GAP_HITS_PER_ROUND
        )
        budget = max(budget, top_k)
        # Track gap queries already attempted so the judge proposes new angles
        # instead of repeating the same gaps every round (progressive feedback).
        tried: list[str] = []
        tried_norm: set[str] = set()
        pending_context_trace_idx: int | None = None

        for round_idx in range(options.max_sufficiency_rounds):
            if pending_context_trace_idx is not None and include_trace:
                trace[pending_context_trace_idx]["context_reevaluated"] = True
                pending_context_trace_idx = None
            verdict = await self.sufficiency_evaluator.evaluate(
                query=processed_query,
                chunks=result.chunks,
                tenant_config=tenant_config,
                tried_gap_queries=tried,
            )

            # Drop gaps already attempted in earlier rounds (defends against the
            # judge repeating them despite the prompt).
            fresh_gaps = []
            round_gap_norms: set[str] = set()
            for gap in verdict.gap_queries:
                normalized = " ".join(gap.split()).casefold()
                if normalized and normalized not in tried_norm and normalized not in round_gap_norms:
                    round_gap_norms.add(normalized)
                    fresh_gaps.append(gap)
                if len(fresh_gaps) == SUFFICIENCY_GAPS_PER_ROUND:
                    break

            if include_trace:
                trace.append(
                    {
                        "step": "sufficiency_check",
                        "round": round_idx + 1,
                        "sufficient": verdict.is_sufficient,
                        "reason": verdict.reason,
                        "status": (
                            "unknown" if verdict.is_sufficient is None
                            else "sufficient" if verdict.is_sufficient
                            else "insufficient"
                        ),
                        "gap_queries": verdict.gap_queries,
                        "fresh_gap_queries": fresh_gaps,
                        "coverage": verdict.coverage,
                    }
                )

            if verdict.is_sufficient is None or verdict.is_sufficient or not fresh_gaps:
                break

            round_groups: list[list[dict[str, Any]]] = []
            below_floor: list[Any] = []
            for gap_q in fresh_gaps:
                tried.append(gap_q)
                tried_norm.add(" ".join(gap_q.split()).casefold())
                gap_structured = QueryParser.parse(gap_q)
                try:
                    gap_result = await self._execute_vector_search(
                        structured_query=gap_structured,
                        tenant_id=tenant_id,
                        document_ids=document_ids,
                        filters=filters,
                        top_k=top_k,
                        options=gap_options,
                        trace=trace,
                        vector_targets=vector_targets,
                        tenant_config=tenant_config,
                        include_trace=include_trace,
                        _rerank_stage="gap",
                    )
                except Exception as e:
                    logger.warning("Gap retrieval failed for %r: %s", gap_q[:80], e)
                    continue
                result.reranking_ms += gap_result.reranking_ms
                # Only reranker-scale scores are comparable with the floor; vector/RRF
                # fallback scores pass through unchanged.
                hits = []
                for c in gap_result.chunks[:top_k]:
                    if (
                        c.get("score_type") == "reranker"
                        and float(c.get("score") or 0.0) < SUFFICIENCY_GAP_MIN_SCORE
                    ):
                        below_floor.append(c.get("chunk_id"))
                    else:
                        hits.append(c)
                if hits:
                    round_groups.append(
                        [
                            {**c, "sufficiency_gap_hit": True, "sufficiency_round": round_idx + 1}
                            for c in hits
                        ]
                    )

            merged, _, _ = await self._merge_candidate_groups(
                [list(result.chunks)] + round_groups,
                query=processed_query,
                top_k=min(budget, len(result.chunks) + SUFFICIENCY_GAP_HITS_PER_ROUND),
                rerank=False,
            )
            # Base chunks win dedupe, so only this round's admitted hits carry its number.
            added = [c for c in merged if c.get("sufficiency_round") == round_idx + 1]
            result.chunks = merged
            if include_trace:
                sufficiency_trace = next(
                    (
                        step for step in reversed(trace)
                        if step.get("step") == "sufficiency_check"
                    ),
                    None,
                )
                if sufficiency_trace is not None:
                    sufficiency_trace["gap_hits_added"] = [c.get("chunk_id") for c in added]
                    sufficiency_trace["gap_hits_below_floor"] = len(below_floor)

            if not added:
                break

            if include_trace:
                trace_entry_idx = next(
                    (
                        idx for idx in range(len(trace) - 1, -1, -1)
                        if trace[idx].get("step") == "sufficiency_check"
                    ),
                    None,
                )
                if trace_entry_idx is not None:
                    pending_context_trace_idx = trace_entry_idx
                    trace_entry = trace[trace_entry_idx]
                    trace_entry["context_reevaluated"] = False
                    if round_idx + 1 == options.max_sufficiency_rounds:
                        trace_entry["context_changed_after_evaluation"] = True

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
        vector_targets: list[VectorSearchTarget],
        tenant_config: dict[str, Any] | None = None,
        include_trace: bool = False,
        _rerank_stage: str = "initial",
    ) -> RetrievalResult:
        """Helper to execute vector search with HyDE and Decomposition support."""
        allowed_document_ids = set(document_ids) if document_ids else None

        # Handle Decomposition
        queries_to_run = [structured_query.cleaned_query]
        if options.use_decomposition:
            queries_to_run = await self.decomposer.decompose(
                structured_query.cleaned_query,
                tenant_config=tenant_config,
            )

        logger.debug("Vector search running %d query variant(s)", len(queries_to_run))
        if include_trace:
            trace.append({"step": "query_variants", "queries": list(queries_to_run)})

        # Resolve embedding service once (tenant_config is constant for the loop) so we
        # can read model/provider for cache-key construction without redundant calls.
        _emb_svc_for_key = self._resolve_embedding_service(tenant_config)
        _cache_embedding_model: str = _emb_svc_for_key.model or ""
        _cache_embedding_provider: str = getattr(_emb_svc_for_key.provider, "provider_name", "") or ""
        _cache_collection_names: list[str] = [t.collection_name for t in vector_targets]
        _cache_search_mode: str = options.search_mode.value if options.search_mode else ""
        # Per-viewer ACL scope: when group enforcement narrows a target to the
        # viewer's visible-document allowlist, that allowlist must be part of the
        # cache key. Otherwise two viewers in the same tenant with different group
        # grants share a cache entry and one receives the other's results.
        _cache_acl_scope: list[str] = sorted(
            {doc_id for t in vector_targets if t.document_ids is not None for doc_id in t.document_ids}
        )

        variant_groups: list[list[dict[str, Any]]] = []
        reranking_ms_total = 0.0

        for q in queries_to_run:
            query_chunks: list[dict[str, Any]] = []
            logger.debug("Vector search processing query variant: %s", q[:120])
            # Handle HyDE
            search_query = q
            if options.use_hyde:
                step_start = time.perf_counter()
                hypotheses = await self.hyde_service.generate_hypothesis(
                    q,
                    tenant_config=tenant_config,
                )
                if hypotheses:
                    search_query = hypotheses[0]  # Use first hypothesis
                    trace.append(
                        {
                            "step": "hyde",
                            "duration_ms": (time.perf_counter() - step_start) * 1000,
                            "hypothesis_preview": search_query[:50] + "...",
                        }
                    )

            # Check result cache for this specific sub-query
            step_start = time.perf_counter()
            cache_filters = {"document_ids": document_ids, **(filters or {})}
            if _cache_acl_scope:
                cache_filters["_acl_scope"] = _cache_acl_scope
            cached_result = await self.result_cache.get(
                search_query,
                tenant_id,
                cache_filters,
                search_mode=_cache_search_mode,
                top_k=top_k,
                embedding_model=_cache_embedding_model,
                embedding_provider=_cache_embedding_provider,
                collection_names=_cache_collection_names,
                rerank_score_floor=self.config.rerank_score_floor,
            )

            logger.debug("Result cache lookup for '%s' hit=%s", search_query, bool(cached_result))

            if cached_result:
                # Use cached chunk IDs to avoid re-embedding and re-searching
                sub_chunks = await self._fetch_chunks_by_ids(
                    cached_result.chunk_ids[:top_k],
                    cached_result.scores[:top_k],
                    (cached_result.score_types or ["unknown"] * len(cached_result.chunk_ids))[:top_k],
                    (cached_result.sources or ["unknown"] * len(cached_result.chunk_ids))[:top_k],
                )
                if allowed_document_ids is not None:
                    sub_chunks = [
                        c for c in sub_chunks if c.get("document_id") in allowed_document_ids
                    ]
                if sub_chunks or not cached_result.chunk_ids:
                    # Real cache hit — either chunks resolved, or the cache
                    # legitimately recorded "no matches" for this query (empty
                    # chunk_ids to begin with, not a resolution failure).
                    #
                    # Staleness is decided on the *resolution* result, before the
                    # floor filter below: "every cached chunk sits under the
                    # floor" is the gate doing its job on a healthy entry, not a
                    # stale entry, and must not send us back to a live search
                    # that would filter the same chunks out again.
                    logger.info("Using cached result for '%s'", search_query)
                    if include_trace:
                        trace.append({
                            "step": "cache_selection",
                            "query": search_query,
                            "cache_hit": True,
                            "chunks": [
                                {
                                    "chunk_id": c.get("chunk_id"),
                                    "document_id": c.get("document_id"),
                                    "score": c.get("score"),
                                    "score_type": c.get("score_type"),
                                    "source": c.get("source"),
                                }
                                for c in sub_chunks
                            ],
                        })

                    # Apply the reranker floor only to scores known to be on the
                    # reranker scale. Legacy cache entries have unknown provenance
                    # and must not be compared with a reranker threshold.
                    if len(queries_to_run) == 1 and self.config.rerank_score_floor is not None:
                        sub_chunks = [
                            c
                            for c in sub_chunks
                            if c.get("score_type") != "reranker"
                            or float(c.get("score", 0.0)) >= self.config.rerank_score_floor
                        ]
                    query_chunks.extend(sub_chunks)
                    variant_groups.append(query_chunks[:top_k])
                    continue

                # Stale cache entry: the cache pointed at chunk_ids, but NONE
                # of them resolved to a real chunk (e.g. a re-ingest replaced
                # them with new ids — see _fetch_chunks_by_ids' `if cid in
                # chunk_map` filter). A cache hit that resolves to zero chunks
                # is a miss, not "zero relevant chunks" — treating it as a hit
                # here made this sub-query (and, if it was the only one,
                # the whole request) come back with 0 chunks even though
                # matching documents exist. Fall through to a real search
                # instead of `continue`-ing past it; the search below
                # repopulates this cache entry with fresh ids, so no explicit
                # invalidation or new TTL handling is needed.
                logger.warning(
                    "Cache hit for '%s' resolved 0/%d cached chunk ids to a "
                    "real chunk (stale entry, likely after a re-ingest) — "
                    "falling back to a live search for this sub-query",
                    search_query,
                    len(cached_result.chunk_ids),
                )

            # Get embedding
            logger.debug("Generating embedding for query variant '%s'", search_query[:120])

            # Resolve correct embedding service for this tenant
            embedding_svc = self._resolve_embedding_service(tenant_config)
            query_embedding = await embedding_svc.embed_single(search_query)

            if not query_embedding:
                logger.warning(f"Embedding failed for query: {search_query}. Skipping search.")
                continue
            logger.debug("Embedding generated for query variant '%s'", search_query[:120])

            # Vector search (Dense or Hybrid)
            search_results = None

            if self.sparse_embedding and self.config.enable_hybrid:
                # Generate sparse embedding and use hybrid search
                sparse_emb = self.sparse_embedding.embed_sparse(search_query)
                if sparse_emb:
                    hybrid_start = time.perf_counter()
                    search_results, target_search_trace = await self._search_vector_targets_hybrid(
                        query_vector=query_embedding,
                        sparse_vector=sparse_emb,
                        vector_targets=vector_targets,
                        limit=self.config.initial_k if self.reranker else top_k,
                        filters=filters,
                    )
                    logger.debug("Hybrid search returned %d merged results", len(search_results))
                    trace.append(
                        {
                            "step": "vector_search",
                            "duration_ms": (time.perf_counter() - hybrid_start) * 1000,
                            "results_count": len(search_results),
                            "query": search_query,
                            "mode": "hybrid",
                            "targets": target_search_trace,
                        }
                    )

            if search_results is None:
                step_start = time.perf_counter()

                search_results, target_search_trace = await self._search_vector_targets(
                    query_vector=query_embedding,
                    vector_targets=vector_targets,
                    limit=self.config.initial_k if self.reranker else top_k,
                    filters=filters,
                )
                logger.debug("Vector search returned %d merged results", len(search_results))
                trace.append(
                    {
                        "step": "vector_search",
                        "duration_ms": (time.perf_counter() - step_start) * 1000,
                        "results_count": len(search_results),
                        "query": search_query,
                        "mode": "dense",
                        "targets": target_search_trace,
                    }
                )
            else:
                trace.append(
                    {
                        "step": "vector_search",
                        "duration_ms": (time.perf_counter() - step_start) * 1000,
                        "results_count": len(search_results),
                        "mode": "hybrid",
                    }
                )

            if allowed_document_ids is not None:
                search_results = [
                    r for r in search_results if r.document_id in allowed_document_ids
                ]

            if include_trace:
                trace.append({
                    "step": "pre_rerank_candidates",
                    "query": search_query,
                    "chunks": [
                        {
                            "chunk_id": r.chunk_id,
                            "document_id": r.document_id,
                            "score": float(r.score),
                            "score_type": getattr(r, "score_type", "cosine"),
                            "source": getattr(r, "source", "vector"),
                        }
                        for r in search_results
                    ],
                })

            # Rerank
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

                    validated = _validated_rerank_results(
                        rerank_result.results,
                        input_count=len(search_results),
                        top_k=top_k,
                    )
                    if validated is None:
                        raise ValueError("malformed or incomplete reranker results")

                    # Reorder results based on validated reranker scores.
                    reranked_results = []
                    for index, score in validated:
                        original = search_results[index]
                        reranked_results.append(
                            SearchResult(
                                chunk_id=original.chunk_id,
                                document_id=original.document_id,
                                tenant_id=original.tenant_id,
                                score=score,
                                score_type="reranker",
                                source=getattr(original, "source", "vector"),
                                metadata=original.metadata,
                                generation_id=getattr(
                                    original,
                                    "generation_id",
                                    original.metadata.get("generation_id"),
                                ),
                            )
                        )
                    rerank_trace = {
                        "step": "rerank",
                        "stage": _rerank_stage,
                        "duration_ms": (time.perf_counter() - step_start) * 1000,
                        "model": self.config.rerank_model,
                        "rerank_attempted": True,
                        **_provider_rerank_timings(rerank_result),
                    }

                    # Relevance floor: drop chunks the reranker scored below the
                    # configured threshold. Applied only here because the floor is
                    # calibrated on the reranker scale; the raw vector scores this
                    # method may fall back to (rerank failure branch below) are on
                    # a different scale and must not be compared against it.
                    floor = (
                        self.config.rerank_score_floor
                        if len(queries_to_run) == 1
                        else None
                    )
                    if floor is not None:
                        kept = [r for r in reranked_results if r.score >= floor]
                        dropped = len(reranked_results) - len(kept)
                        if dropped:
                            logger.info(
                                "Rerank floor %.3f dropped %d/%d chunks for '%s'",
                                floor,
                                dropped,
                                len(reranked_results),
                                search_query[:80],
                            )
                        rerank_trace["floor"] = floor
                        rerank_trace["dropped_below_floor"] = dropped
                        reranked_results = kept

                    search_results = reranked_results

                    trace.append(rerank_trace)
                    reranking_ms_total += rerank_trace["duration_ms"]

                except Exception as e:
                    failed_duration_ms = (time.perf_counter() - step_start) * 1000
                    reranking_ms_total += failed_duration_ms
                    trace.append(
                        {
                            "step": "rerank",
                            "stage": _rerank_stage,
                            "duration_ms": failed_duration_ms,
                            "model": self.config.rerank_model,
                            "rerank_attempted": True,
                            "status": "failed",
                        }
                    )
                    logger.warning(f"Reranking failed, using vector scores: {e}")
                    search_results = search_results[:top_k]

            else:
                search_results = search_results[:top_k]

            if include_trace:
                trace.append({
                    "step": "post_rerank_candidates",
                    "query": search_query,
                    "chunks": [
                        {
                            "chunk_id": r.chunk_id,
                            "document_id": r.document_id,
                            "score": float(r.score),
                            "score_type": getattr(r, "score_type", "cosine"),
                            "source": getattr(r, "source", "vector"),
                        }
                        for r in search_results
                    ],
                })

            # Fallback: Check for missing content and fetch from DB
            missing_content_ids = []
            for r in search_results:
                if not r.metadata.get("content"):
                    missing_content_ids.append(r.chunk_id)

            if missing_content_ids:
                logger.info(
                    f"METRIC: Resilient Content Fallback Triggered for {len(missing_content_ids)} chunks"
                )
                try:
                    from opentelemetry import trace

                    span = trace.get_current_span()
                    span.add_event(
                        "resilient_fallback_triggered",
                        attributes={"chunk_count": len(missing_content_ids)},
                    )
                    span.set_attribute("retrieval.fallback_count", len(missing_content_ids))
                except ImportError:
                    pass

                try:
                    db_chunks_list = await self.document_repository.get_chunks(missing_content_ids)
                    db_chunks = {c.id: c.content for c in db_chunks_list}

                    for r in search_results:
                        if r.chunk_id in db_chunks:
                            r.metadata["content"] = db_chunks[r.chunk_id]
                except Exception as e:
                    logger.warning(f"Failed to fetch missing content from repo: {e}")

            # Build chunks and cache
            sub_chunks_to_cache = []
            for r in search_results:
                chunk_data = {
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "score": float(r.score),
                    "score_type": getattr(r, "score_type", "cosine"),
                    "source": getattr(r, "source", "vector"),
                    "content": r.metadata.get("content", ""),
                }
                sub_chunks_to_cache.append(chunk_data)
                query_chunks.append(chunk_data)

            variant_groups.append(query_chunks[:top_k])

            # Cache results for this sub-query
            await self.result_cache.set(
                query=search_query,
                tenant_id=tenant_id,
                chunk_ids=[c["chunk_id"] for c in sub_chunks_to_cache],
                scores=[c["score"] for c in sub_chunks_to_cache],
                score_types=[c["score_type"] for c in sub_chunks_to_cache],
                sources=[c["source"] for c in sub_chunks_to_cache],
                filters=cache_filters,
                search_mode=_cache_search_mode,
                top_k=top_k,
                embedding_model=_cache_embedding_model,
                embedding_provider=_cache_embedding_provider,
                collection_names=_cache_collection_names,
                rerank_score_floor=self.config.rerank_score_floor,
            )

        if len(queries_to_run) > 1:
            common_rerank_attempted = self.reranker is not None and any(variant_groups)
            common_rerank_timings: dict[str, float] = {}
            final_chunks, common_reranking_ms, _ = await self._merge_candidate_groups(
                variant_groups,
                query=structured_query.cleaned_query,
                top_k=top_k,
                provider_timings=common_rerank_timings if include_trace else None,
            )
            reranking_ms_total += common_reranking_ms
            if include_trace:
                trace.append(
                    {
                        "step": "common_query_rerank",
                        "stage": "query_variant_common",
                        "rerank_attempted": common_rerank_attempted,
                        "query": structured_query.cleaned_query,
                        "duration_ms": common_reranking_ms,
                        **common_rerank_timings,
                        "chunks": [
                            {
                                "chunk_id": c.get("chunk_id"),
                                "document_id": c.get("document_id"),
                                "score": c.get("score"),
                                "score_type": c.get("score_type"),
                                "source": c.get("source"),
                            }
                            for c in final_chunks
                        ],
                    }
                )
        else:
            final_chunks = variant_groups[0] if variant_groups else []
            final_chunks.sort(key=lambda x: x["score"], reverse=True)
            final_chunks = final_chunks[:top_k]
        if include_trace:
            trace.append({
                "step": "final_selection",
                "chunks": [
                    {
                        "chunk_id": c.get("chunk_id"),
                        "document_id": c.get("document_id"),
                        "score": c.get("score"),
                        "score_type": c.get("score_type"),
                        "source": c.get("source"),
                    }
                    for c in final_chunks
                ],
            })

        return RetrievalResult(
            chunks=final_chunks,
            query=structured_query.cleaned_query,
            tenant_id=tenant_id,
            latency_ms=0,  # Updated by caller
            trace=trace,
            reranking_ms=reranking_ms_total,
        )

    async def _fetch_chunks_by_ids(
        self,
        chunk_ids: list[str],
        scores: list[float],
        score_types: list[str] | None = None,
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch chunk content from repository."""
        if not chunk_ids:
            return []

        try:
            db_chunks = await self.document_repository.get_chunks(chunk_ids)
            chunk_map = {c.id: c for c in db_chunks}

            results = []
            aligned_score_types = score_types or ["unknown"] * len(chunk_ids)
            aligned_sources = sources or ["unknown"] * len(chunk_ids)
            for cid, score, score_type, source in zip(
                chunk_ids, scores, aligned_score_types, aligned_sources, strict=False
            ):
                if cid in chunk_map:
                    chunk = chunk_map[cid]
                    results.append(
                        {
                            "chunk_id": chunk.id,
                            "document_id": chunk.document_id,
                            "content": chunk.content,
                            "metadata": chunk.metadata_,
                            "score": score,
                            "score_type": score_type,
                            "source": source,
                        }
                    )
            return results
        except Exception as e:
            logger.error(f"Failed to fetch chunks from repository: {e}")
            return []

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
