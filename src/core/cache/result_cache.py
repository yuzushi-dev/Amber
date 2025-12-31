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
    except ImportError:
        raise ImportError("redis package is required. Install with: pip install redis>=5.0.0")


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
    ) -> str:
        """Create a hash key for a search request."""
        data = {
            "query": query.strip().lower(),
            "tenant_id": tenant_id,
            "filters": filters or {},
        }
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()[:32]

    def _make_key(self, request_hash: str) -> str:
        """Create a Redis key for results."""
        return f"{self.config.key_prefix}:results:{request_hash}"

    def _make_tenant_key(self, tenant_id: str) -> str:
        """Create a Redis key for tenant timestamp."""
        return f"{self.config.key_prefix}:tenant_ts:{tenant_id}"

    async def get(
        self,
        query: str,
        tenant_id: str,
        filters: dict[str, Any] | None = None,
    ) -> CachedResult | None:
        """
        Get cached retrieval result.
        
        Args:
            query: The search query
            tenant_id: Tenant ID
            filters: Optional search filters
            
        Returns:
            CachedResult or None if not found/stale
        """
        if not self.config.enabled:
            return None

        try:
            client = await self._get_client()
            request_hash = self._hash_request(query, tenant_id, filters)
            key = self._make_key(request_hash)

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
            
        Returns:
            True if cached successfully
        """
        if not self.config.enabled:
            return False

        try:
            from datetime import datetime

            client = await self._get_client()
            request_hash = self._hash_request(query, tenant_id, filters)
            key = self._make_key(request_hash)
            ttl = ttl or self.config.ttl_seconds

            data = json.dumps({
                "chunk_ids": chunk_ids,
                "scores": scores,
                "cached_at": datetime.utcnow().isoformat(),
                "query_hash": request_hash,
            })

            await client.setex(key, ttl, data)
            logger.debug(f"Cached results for query: {query[:50]}...")
            return True

        except Exception as e:
            logger.warning(f"Cache set failed: {e}")
            return False

    async def invalidate_tenant(self, tenant_id: str) -> bool:
        """
        Invalidate all cached results for a tenant.
        
        Call this when documents are added/modified/deleted.
        """
        try:
            from datetime import datetime

            client = await self._get_client()
            tenant_key = self._make_tenant_key(tenant_id)

            # Set timestamp to now, making all previous cache entries stale
            await client.set(tenant_key, datetime.utcnow().isoformat())

            logger.info(f"Invalidated result cache for tenant {tenant_id}")
            return True

        except Exception as e:
            logger.warning(f"Cache invalidation failed: {e}")
            return False

    async def clear_tenant(self, tenant_id: str) -> int:
        """Clear all cached results for a tenant."""
        try:
            client = await self._get_client()
            pattern = f"{self.config.key_prefix}:results:*"

            # Note: This is not efficient for large caches
            # A better approach would be to prefix keys with tenant_id
            deleted = 0
            async for key in client.scan_iter(match=pattern):
                data = await client.get(key)
                if data:
                    try:
                        cached = json.loads(data)
                        # We can't filter by tenant without tenant in key
                        # For now, just use invalidation instead
                        pass
                    except Exception:
                        pass


            # Update the tenant timestamp
            await self.invalidate_tenant(tenant_id)

            logger.info(f"Cleared cache for tenant {tenant_id}")
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
            await self._client.close()
            self._client = None
