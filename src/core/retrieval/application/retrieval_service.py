"""
Retrieval Service
=================

Unified retrieval pipeline combining vector search, caching, and reranking.
"""

import inspect
import logging
import time
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
from src.core.retrieval.application.search.graph import GraphSearcher
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
            factory = build_provider_factory(
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                ollama_base_url=ollama_base_url,
                default_embedding_provider=default_embedding_provider,
                default_embedding_model=default_embedding_model,
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

        # Use injected neo4j_client (already set in __init__ start)
        self.graph_searcher = GraphSearcher(self.neo4j_client)

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
                limit=limit,
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
        return merged_results, target_trace


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
                limit=limit,
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
        return merged_results, target_trace

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
        resolved_scopes = query_scopes or resolve_query_scopes(tenant_id)
        resolved_tenant_id = resolved_scopes.effective_tenant_id
        if include_trace:
            trace.append(
                {
                    "step": "resolve_query_scopes",
                    "effective_tenant_id": resolved_scopes.effective_tenant_id,
                    "vector_scopes": resolved_scopes.vector_scopes,
                    "graph_scopes": resolved_scopes.graph_scopes,
                }
            )
        tenant_config = await self._get_effective_tenant_config(resolved_tenant_id)

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
        all_document_ids = list(set((document_ids or []) + (structured_query.document_ids or [])))
        all_filters = {**(filters or {})}
        if structured_query.tags:
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
        _tax_edition = _explicit_edition or _inferred_edition
        _tax_audience = _explicit_audience or (_tax_ctx.audience if _tax_ctx.audience != "unknown" else None)
        _tax_source_family = _explicit_source_family

        _taxonomy_doc_ids: list[str] | None = None
        _broadening_stage = "none"

        _has_taxonomy_signal = bool(_tax_edition or _tax_audience or _tax_source_family)
        if _has_taxonomy_signal and hasattr(self.document_repository, "list_visible_document_ids_by_taxonomy"):
            _primary_scope = resolved_scopes.effective_tenant_id

            # Stage 1: strict (edition + audience + source_family)
            _strict_ids = await self.document_repository.list_visible_document_ids_by_taxonomy(
                viewer_tenant_id=_primary_scope,
                owner_tenant_id=_primary_scope,
                candidate_document_ids=all_document_ids or None,
                edition=_tax_edition,
                audience=_tax_audience,
                source_family=_tax_source_family,
            )

            if _strict_ids:
                _taxonomy_doc_ids = _strict_ids
                _broadening_stage = "strict"
            elif _tax_edition and _tax_audience:
                # Stage 2: same edition, any audience
                _broad2 = await self.document_repository.list_visible_document_ids_by_taxonomy(
                    viewer_tenant_id=_primary_scope,
                    owner_tenant_id=_primary_scope,
                    candidate_document_ids=all_document_ids or None,
                    edition=_tax_edition,
                )
                if _broad2:
                    _taxonomy_doc_ids = _broad2
                    _broadening_stage = "edition_only"
                else:
                    # Stage 3: any edition, same audience
                    _broad3 = await self.document_repository.list_visible_document_ids_by_taxonomy(
                        viewer_tenant_id=_primary_scope,
                        owner_tenant_id=_primary_scope,
                        candidate_document_ids=all_document_ids or None,
                        audience=_tax_audience,
                    )
                    if _broad3:
                        _taxonomy_doc_ids = _broad3
                        _broadening_stage = "audience_only"
                    else:
                        # Stage 4: unfiltered fallback (low confidence or empty corpus)
                        _broadening_stage = "unfiltered"

            if include_trace:
                trace.append({
                    "step": "taxonomy_routing",
                    "inferred_edition": _tax_ctx.edition,
                    "inferred_audience": _tax_ctx.audience,
                    "explicit_edition": _explicit_edition,
                    "explicit_audience": _explicit_audience,
                    "confidence": _tax_ctx.confidence,
                    "broadening_stage": _broadening_stage,
                    "strict_candidate_count": len(_strict_ids) if _has_taxonomy_signal else None,
                    "taxonomy_doc_ids_count": len(_taxonomy_doc_ids) if _taxonomy_doc_ids else 0,
                })

        if _taxonomy_doc_ids is not None:
            all_document_ids = _taxonomy_doc_ids

        # Step 3: Query Routing
        _router_start = time.perf_counter()
        search_mode = await self.router.route(
            structured_query.cleaned_query,
            explicit_mode=options.search_mode,
            tenant_config=tenant_config,
        )
        _router_latency_ms = (time.perf_counter() - _router_start) * 1000

        # SECURITY: STRUCTURED runs tenant-scoped Cypher with NO group ACL (Neo4j
        # has no Postgres-RLS backstop), and options.search_mode is a public request
        # field the router honours verbatim — so a caller can ask for it explicitly.
        # Under group enforcement the mode is refused here and the query falls
        # through to the ACL-enforced vector path below. Guarding at this single
        # point covers every caller of retrieve(): stream, non-stream, agent tool
        # and drift.
        _structured_allowed = not getattr(resolved_scopes, "enforce_groups", False)
        if not _structured_allowed and search_mode == SearchMode.STRUCTURED:
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
                )
                result = RetrievalResult(
                    chunks=res["candidates"],
                    query=query,
                    tenant_id=resolved_tenant_id,
                    latency_ms=0,
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
                )
        except Exception as e:
            logger.error(f"Retrieval failed for mode {search_mode}: {e}")
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
            )

        # Step 9: Sufficient-context gate + iterative retrieval.
        # Only meaningful for vector-based modes (GLOBAL/DRIFT do their own
        # iteration; STRUCTURED returns tabular rows). Gated by option, off by
        # default — fails open so it never blocks a response.
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

        # Record latency for circuit breaker
        total_latency = (time.perf_counter() - start_time) * 1000
        self.circuit_breaker.record_latency(total_latency)

        result.latency_ms = total_latency
        result.search_mode = search_mode.value
        result.router_latency_ms = _router_latency_ms
        if not include_trace:
            result.trace = []
        else:
            result.trace = trace

        return result

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
        through vector search and merges new chunks into `result` in place.
        Mutates `result.chunks` (kept score-sorted, capped at top_k).
        """
        seen_ids = {c.get("chunk_id") for c in result.chunks}
        # Decomposition off for gap queries to avoid combinatorial fan-out.
        gap_options = options.model_copy(update={"use_decomposition": False})
        # Context budget: gap chunks are ADDED (the loop fills gaps), not capped
        # back to top_k — otherwise narrow gap chunks evict the original best
        # chunks and the loop hurts more than it helps.
        budget = options.sufficiency_max_chunks or (
            top_k + options.max_sufficiency_rounds * 3
        )
        budget = max(budget, top_k)
        # Track gap queries already attempted so the judge proposes new angles
        # instead of repeating the same gaps every round (progressive feedback).
        tried: list[str] = []
        tried_norm: set[str] = set()

        for round_idx in range(options.max_sufficiency_rounds):
            verdict = await self.sufficiency_evaluator.evaluate(
                query=processed_query,
                chunks=result.chunks,
                tenant_config=tenant_config,
                tried_gap_queries=tried,
            )

            # Drop gaps already attempted in earlier rounds (defends against the
            # judge repeating them despite the prompt).
            fresh_gaps = [
                g for g in verdict.gap_queries if g.strip().lower() not in tried_norm
            ]

            if include_trace:
                trace.append(
                    {
                        "step": "sufficiency_check",
                        "round": round_idx + 1,
                        "sufficient": verdict.is_sufficient,
                        "reason": verdict.reason,
                        "gap_queries": verdict.gap_queries,
                        "fresh_gap_queries": fresh_gaps,
                    }
                )

            # Stop when sufficient, or when no genuinely new gap query remains.
            if verdict.is_sufficient or not fresh_gaps:
                break

            added = 0
            for gap_q in fresh_gaps:
                tried.append(gap_q)
                tried_norm.add(gap_q.strip().lower())
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
                    )
                except Exception as e:
                    logger.warning("Gap retrieval failed for %r: %s", gap_q[:80], e)
                    continue

                for c in gap_result.chunks:
                    cid = c.get("chunk_id")
                    if cid not in seen_ids:
                        result.chunks.append(c)
                        seen_ids.add(cid)
                        added += 1

            # Keep score-sorted and bounded by the expanded budget; stop early if
            # nothing new surfaced. seen_ids stays cumulative so trimmed-out
            # chunks are not re-fetched.
            result.chunks.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            result.chunks = result.chunks[:budget]

            if added == 0:
                break

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
    ) -> RetrievalResult:
        """Helper to execute vector search with HyDE and Decomposition support."""

        # Handle Decomposition
        queries_to_run = [structured_query.cleaned_query]
        if options.use_decomposition:
            queries_to_run = await self.decomposer.decompose(
                structured_query.cleaned_query,
                tenant_config=tenant_config,
            )

        logger.debug("Vector search running %d query variant(s)", len(queries_to_run))

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

        all_chunks = []
        seen_chunk_ids = set()

        for q in queries_to_run:
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
                logger.info("Using cached result for '%s'", search_query)
                sub_chunks = await self._fetch_chunks_by_ids(
                    cached_result.chunk_ids[:top_k],
                    cached_result.scores[:top_k],
                )
                # Cached scores are post-rerank scores (see sub_chunks_to_cache
                # below). The floor is part of the cache key, so an entry read back
                # here was already written under this same floor; this filter is the
                # belt-and-braces half of that pair, and it is what keeps the gate
                # honest if a future writer ever caches without keying by the floor.
                if self.config.rerank_score_floor is not None:
                    sub_chunks = [
                        c
                        for c in sub_chunks
                        if float(c.get("score", 0.0)) >= self.config.rerank_score_floor
                    ]
                for c in sub_chunks:
                    if c["chunk_id"] not in seen_chunk_ids:
                        all_chunks.append(c)
                        seen_chunk_ids.add(c["chunk_id"])
                continue

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

                    rerank_trace = {
                        "step": "rerank",
                        "duration_ms": (time.perf_counter() - step_start) * 1000,
                        "model": self.config.rerank_model,
                    }

                    # Relevance floor: drop chunks the reranker scored below the
                    # configured threshold. Applied only here because the floor is
                    # calibrated on the reranker scale; the raw vector scores this
                    # method may fall back to (rerank failure branch below) are on
                    # a different scale and must not be compared against it.
                    floor = self.config.rerank_score_floor
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

                except Exception as e:
                    logger.warning(f"Reranking failed, using vector scores: {e}")
                    search_results = search_results[:top_k]

            else:
                search_results = search_results[:top_k]

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
                search_mode=_cache_search_mode,
                top_k=top_k,
                embedding_model=_cache_embedding_model,
                embedding_provider=_cache_embedding_provider,
                collection_names=_cache_collection_names,
                rerank_score_floor=self.config.rerank_score_floor,
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
        """Fetch chunk content from repository."""
        if not chunk_ids:
            return []

        try:
            db_chunks = await self.document_repository.get_chunks(chunk_ids)
            chunk_map = {c.id: c for c in db_chunks}

            results = []
            for cid, score in zip(chunk_ids, scores, strict=False):
                if cid in chunk_map:
                    chunk = chunk_map[cid]
                    results.append(
                        {
                            "chunk_id": chunk.id,
                            "document_id": chunk.document_id,
                            "content": chunk.content,
                            "metadata": chunk.metadata_,
                            "score": score,
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
