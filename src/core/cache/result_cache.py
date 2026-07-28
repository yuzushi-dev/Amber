"""
Result Cache
============

Cache for retrieval results to avoid repeating expensive searches.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _get_redis():
    """Get redis module with lazy loading."""
    try:
        import redis.asyncio as redis

        return redis
    except ImportError as e:
        raise ImportError(
            "redis package is required. Install with: pip install redis>=5.0.0"
        ) from e


@dataclass
class ResultCacheConfig:
    """Result cache configuration."""

    redis_url: str = "redis://localhost:6379/0"
    ttl_seconds: int = 3600  # 1 hour
    key_prefix: str = "result_cache"
    enabled: bool = True


@dataclass
class CachedResult:
    """Cached retrieval result."""

    chunk_ids: list[str]
    scores: list[float]
    cached_at: str
    tenant_id: str


class ResultCache:
    """
    Cache for retrieval results.

    Stores (query, tenant, filters) -> chunk IDs mapping
    to avoid repeating expensive vector searches.

    Invalidation Strategy:
    - Each tenant has a `last_update_ts` timestamp
    - When a document is added/modified, increment this timestamp
    - Cache entries are ignored if their timestamp < last_update_ts

    Usage:
        cache = ResultCache(config)

        # Check cache
        result = await cache.get("query", "tenant_123")
        if result is None:
            chunks = await search(...)
            await cache.set("query", "tenant_123", chunk_ids, scores)
    """

    def __init__(self, config: ResultCacheConfig | None = None):
        self.config = config or ResultCacheConfig()
        self._client = None
        self._stats = {"hits": 0, "misses": 0, "stale": 0}

    async def _get_client(self):
        """Get or create Redis client."""
        if self._client is None:
            redis = _get_redis()
            self._client = redis.from_url(
                self.config.redis_url,
                decode_responses=True,
            )
        return self._client

    def _hash_request(
        self,
        query: str,
        tenant_id: str,
        filters: dict[str, Any] | None = None,
        search_mode: str | None = None,
        top_k: int | None = None,
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
        collection_names: list[str] | None = None,
        rerank_score_floor: float | None = None,
    ) -> str:
        """Create a hash key for a search request.

        All dimensions that affect the result set must be included:
        - query + tenant + filters: the original key components
        - search_mode: BASIC / LOCAL / GLOBAL / DRIFT produce different result shapes
        - top_k: cached list may be smaller than a new request's top_k, so we key by it
        - embedding_model / embedding_provider: different models produce different vectors
        - collection_names: different collections hold different data
        - rerank_score_floor: entries are stored AFTER the floor drops chunks, so a
          cached entry only holds the chunks that survived the floor in force at
          write time. Keying by it makes a floor change self-invalidating instead
          of requiring a manual cache invalidation to take effect.
        tenant_id is both in the hash payload (defense) and in the key prefix (for SCAN).
        """
        data = {
            "query": query.strip().lower(),
            "tenant_id": tenant_id,
            "filters": filters or {},
            "search_mode": search_mode or "",
            "top_k": top_k,
            "embedding_model": embedding_model or "",
            "embedding_provider": embedding_provider or "",
            "collection_names": sorted(collection_names or []),
            "rerank_score_floor": rerank_score_floor,
        }
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()[:32]

    def _make_key(self, tenant_id: str, request_hash: str) -> str:
        """Create a Redis key for results, namespaced by tenant for SCAN-based invalidation."""
        return f"result:{tenant_id}:{request_hash}"

    def _make_tenant_key(self, tenant_id: str) -> str:
        """Create a Redis key for tenant timestamp."""
        return f"{self.config.key_prefix}:tenant_ts:{tenant_id}"

    async def get(
        self,
        query: str,
        tenant_id: str,
        filters: dict[str, Any] | None = None,
        search_mode: str | None = None,
        top_k: int | None = None,
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
        collection_names: list[str] | None = None,
        rerank_score_floor: float | None = None,
    ) -> CachedResult | None:
        """
        Get cached retrieval result.

        Args:
            query: The search query
            tenant_id: Tenant ID
            filters: Optional search filters
            search_mode: The resolved search mode (affects result shape)
            top_k: Number of results requested
            embedding_model: Resolved embedding model name
            embedding_provider: Resolved embedding provider name
            collection_names: Active vector collection names searched
            rerank_score_floor: Relevance floor in force (part of the key)

        Returns:
            CachedResult or None if not found/stale
        """
        if not self.config.enabled:
            return None

        try:
            client = await self._get_client()
            request_hash = self._hash_request(
                query, tenant_id, filters,
                search_mode=search_mode,
                top_k=top_k,
                embedding_model=embedding_model,
                embedding_provider=embedding_provider,
                collection_names=collection_names,
                rerank_score_floor=rerank_score_floor,
            )
            key = self._make_key(tenant_id, request_hash)

            data = await client.get(key)
            if not data:
                self._stats["misses"] += 1
                return None

            result = json.loads(data)

            # Check staleness
            tenant_key = self._make_tenant_key(tenant_id)
            last_update = await client.get(tenant_key)

            if last_update and result.get("cached_at", "") < last_update:
                self._stats["stale"] += 1
                logger.debug(f"Cache entry stale for tenant {tenant_id}")
                return None

            self._stats["hits"] += 1
            logger.debug(f"Cache hit for query: {query[:50]}...")

            return CachedResult(
                chunk_ids=result["chunk_ids"],
                scores=result["scores"],
                cached_at=result["cached_at"],
                tenant_id=tenant_id,
            )

        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
            return None

    async def set(
        self,
        query: str,
        tenant_id: str,
        chunk_ids: list[str],
        scores: list[float],
        filters: dict[str, Any] | None = None,
        ttl: int | None = None,
        search_mode: str | None = None,
        top_k: int | None = None,
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
        collection_names: list[str] | None = None,
        rerank_score_floor: float | None = None,
    ) -> bool:
        """
        Cache a retrieval result.

        Args:
            query: The search query
            tenant_id: Tenant ID
            chunk_ids: List of retrieved chunk IDs
            scores: Corresponding similarity scores
            filters: Optional search filters used
            ttl: Optional TTL override
            search_mode: The resolved search mode (affects result shape)
            top_k: Number of results requested
            embedding_model: Resolved embedding model name
            embedding_provider: Resolved embedding provider name
            collection_names: Active vector collection names searched
            rerank_score_floor: Relevance floor in force (part of the key)

        Returns:
            True if cached successfully
        """
        if not self.config.enabled:
            return False

        try:
            from datetime import UTC, datetime

            client = await self._get_client()
            request_hash = self._hash_request(
                query, tenant_id, filters,
                search_mode=search_mode,
                top_k=top_k,
                embedding_model=embedding_model,
                embedding_provider=embedding_provider,
                collection_names=collection_names,
                rerank_score_floor=rerank_score_floor,
            )
            key = self._make_key(tenant_id, request_hash)
            ttl = ttl or self.config.ttl_seconds

            data = json.dumps(
                {
                    "chunk_ids": chunk_ids,
                    "scores": scores,
                    "cached_at": datetime.now(UTC).isoformat(),
                    "query_hash": request_hash,
                }
            )

            await client.setex(key, ttl, data)
            logger.debug(f"Cached results for query: {query[:50]}...")
            return True

        except Exception as e:
            logger.warning(f"Cache set failed: {e}")
            return False

    async def invalidate_tenant(self, tenant_id: str) -> bool:
        """
        Invalidate all cached results for a tenant by deleting all keys under
        the result:{tenant_id}:* namespace.

        Call this when documents are added/modified/deleted.
        """
        try:
            deleted = await self.clear_tenant(tenant_id)
            logger.info(f"Invalidated result cache for tenant {tenant_id} ({deleted} keys deleted)")
            return True

        except Exception as e:
            logger.warning(f"Cache invalidation failed: {e}")
            return False

    async def clear_tenant(self, tenant_id: str) -> int:
        """
        Clear all cached results for a tenant.

        Keys are namespaced as result:{tenant_id}:{hash}, so we can SCAN
        exactly the tenant's entries without inspecting values or iterating
        the whole keyspace.
        """
        try:
            client = await self._get_client()
            pattern = f"result:{tenant_id}:*"

            deleted = 0
            keys_to_delete = []
            async for key in client.scan_iter(match=pattern):
                keys_to_delete.append(key)

            if keys_to_delete:
                deleted = await client.delete(*keys_to_delete)

            logger.info(f"Cleared {deleted} cache entries for tenant {tenant_id}")
            return deleted

        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")
            return 0

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"] + self._stats["stale"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0

        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "stale": self._stats["stale"],
            "hit_rate": round(hit_rate, 3),
            "enabled": self.config.enabled,
        }

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
