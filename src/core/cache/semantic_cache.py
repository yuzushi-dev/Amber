"""
Semantic Cache
==============

Cache for query embeddings to avoid re-embedding identical queries.
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
        raise ImportError("redis package is required. Install with: pip install redis>=5.0.0") from e


@dataclass
class CacheConfig:
    """Cache configuration."""

    redis_url: str = "redis://localhost:6379/0"
    ttl_seconds: int = 86400  # 24 hours
    key_prefix: str = "semantic_cache"
    enabled: bool = True


class SemanticCache:
    """
    Cache for query embeddings.

    Stores embeddings keyed by query hash to avoid re-embedding
    identical or near-identical queries.

    Usage:
        cache = SemanticCache(config)

        # Check cache
        embedding = await cache.get("What is GraphRAG?")
        if embedding is None:
            embedding = await embed_query("What is GraphRAG?")
            await cache.set("What is GraphRAG?", embedding)
    """

    def __init__(self, config: CacheConfig | None = None):
        self.config = config or CacheConfig()
        self._client = None
        self._stats = {"hits": 0, "misses": 0}

    async def _get_client(self):
        """Get or create Redis client."""
        if self._client is None:
            redis = _get_redis()
            self._client = redis.from_url(
                self.config.redis_url,
                decode_responses=False,  # We store bytes
            )
        return self._client

    def _hash_query(self, query: str) -> str:
        """Create a hash key for a query."""
        normalized = query.strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    def _make_key(self, query_hash: str) -> str:
        """Create a Redis key."""
        return f"{self.config.key_prefix}:embedding:{query_hash}"

    async def get(self, query: str) -> list[float] | None:
        """
        Get cached embedding for a query.

        Args:
            query: The query string

        Returns:
            Cached embedding or None if not found
        """
        if not self.config.enabled:
            return None

        try:
            client = await self._get_client()
            key = self._make_key(self._hash_query(query))

            data = await client.get(key)
            if data:
                self._stats["hits"] += 1
                embedding = json.loads(data)
                logger.debug(f"Cache hit for query: {query[:50]}...")
                return embedding

            self._stats["misses"] += 1
            return None

        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
            return None

    async def set(
        self,
        query: str,
        embedding: list[float],
        ttl: int | None = None,
    ) -> bool:
        """
        Cache an embedding for a query.

        Args:
            query: The query string
            embedding: The embedding vector
            ttl: Optional TTL override

        Returns:
            True if cached successfully
        """
        if not self.config.enabled:
            return False

        try:
            client = await self._get_client()
            key = self._make_key(self._hash_query(query))
            ttl = ttl or self.config.ttl_seconds

            data = json.dumps(embedding)
            await client.setex(key, ttl, data)

            logger.debug(f"Cached embedding for query: {query[:50]}...")
            return True

        except Exception as e:
            logger.warning(f"Cache set failed: {e}")
            return False

    async def delete(self, query: str) -> bool:
        """Delete a cached embedding."""
        if not self.config.enabled:
            return False

        try:
            client = await self._get_client()
            key = self._make_key(self._hash_query(query))
            await client.delete(key)
            return True

        except Exception as e:
            logger.warning(f"Cache delete failed: {e}")
            return False

    async def clear(self) -> int:
        """Clear all cached embeddings."""
        try:
            client = await self._get_client()
            pattern = f"{self.config.key_prefix}:embedding:*"

            keys = []
            async for key in client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                await client.delete(*keys)

            logger.info(f"Cleared {len(keys)} cached embeddings")
            return len(keys)

        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")
            return 0

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0

        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": round(hit_rate, 3),
            "enabled": self.config.enabled,
        }

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
