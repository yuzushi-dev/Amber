"""
Rate Limiter Core Logic
=======================

Redis-backed sliding window rate limiting.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum

from redis.asyncio import Redis

from src.api.config import settings

logger = logging.getLogger(__name__)


class RateLimitCategory(str, Enum):
    """Rate limit categories for different endpoint types."""

    GENERAL = "general"
    QUERY = "query"
    UPLOAD = "upload"


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: int  # Unix timestamp
    retry_after: int | None = None  # Seconds until retry allowed


class RateLimiter:
    """
    Redis-backed sliding window rate limiter.

    Uses a sliding window algorithm with Redis sorted sets
    for accurate rate limiting across multiple instances.
    """

    def __init__(self, redis_url: str | None = None):
        """
        Initialize the rate limiter.

        Args:
            redis_url: Redis connection URL (defaults to settings)
        """
        self.redis_url = redis_url or settings.db.redis_url
        self._redis: Redis | None = None

    async def _get_redis(self) -> Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = Redis.from_url(
                self.redis_url,
                decode_responses=True,
            )
        return self._redis

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    def _get_limits(self, category: RateLimitCategory) -> tuple[int, int]:
        """
        Get rate limits for a category.

        Returns:
            tuple[int, int]: (requests_per_minute, window_seconds)
        """
        if category == RateLimitCategory.QUERY:
            return settings.rate_limits.queries_per_minute, 60
        elif category == RateLimitCategory.UPLOAD:
            return settings.rate_limits.uploads_per_hour, 3600
        else:  # GENERAL
            return settings.rate_limits.requests_per_minute, 60

    async def check(
        self,
        tenant_id: str,
        category: RateLimitCategory = RateLimitCategory.GENERAL,
    ) -> RateLimitResult:
        """
        Check and record a rate limit request.

        Uses a sliding window with Redis sorted sets.
        Each request is recorded with its timestamp as the score.
        Old entries outside the window are removed.

        Args:
            tenant_id: Tenant identifier for isolation
            category: Rate limit category

        Returns:
            RateLimitResult: Whether request is allowed and limit info
        """
        limit, window = self._get_limits(category)
        now = int(time.time())
        window_start = now - window

        key = f"ratelimit:{tenant_id}:{category.value}"

        try:
            redis = await self._get_redis()

            # Use pipeline for atomic operations
            async with redis.pipeline(transaction=True) as pipe:
                # Remove old entries outside the window
                pipe.zremrangebyscore(key, 0, window_start)
                # Count current requests in window
                pipe.zcard(key)
                # Add current request with timestamp as score
                pipe.zadd(key, {f"{now}:{time.perf_counter_ns()}": now})
                # Set expiry on the key
                pipe.expire(key, window)

                results = await pipe.execute()

            current_count = results[1]  # zcard result

            if current_count >= limit:
                # Get the oldest entry to calculate retry-after
                oldest = await redis.zrange(key, 0, 0, withscores=True)
                if oldest:
                    oldest_time = int(oldest[0][1])
                    retry_after = oldest_time + window - now
                else:
                    retry_after = window

                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_at=now + retry_after,
                    retry_after=max(1, retry_after),
                )

            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=max(0, limit - current_count - 1),
                reset_at=now + window,
            )

        except Exception as e:
            # On Redis failure, allow the request but log
            logger.error(f"Rate limiter error: {e}. Allowing request.")
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit - 1,
                reset_at=now + window,
            )

    async def check_concurrency(
        self,
        tenant_id: str,
        resource: str,
        max_concurrent: int,
    ) -> tuple[bool, int]:
        """
        Check concurrent resource usage.

        Args:
            tenant_id: Tenant identifier
            resource: Resource type (e.g., "ingestion")
            max_concurrent: Maximum concurrent allowed

        Returns:
            tuple[bool, int]: (allowed, current_count)
        """
        key = f"concurrent:{tenant_id}:{resource}"

        try:
            redis = await self._get_redis()
            current = await redis.get(key)
            current_count = int(current) if current else 0

            if current_count >= max_concurrent:
                return False, current_count

            return True, current_count

        except Exception as e:
            logger.error(f"Concurrency check error: {e}. Allowing request.")
            return True, 0

    async def increment_concurrent(self, tenant_id: str, resource: str) -> int:
        """Increment concurrent count. Returns new count."""
        key = f"concurrent:{tenant_id}:{resource}"
        try:
            redis = await self._get_redis()
            count = await redis.incr(key)
            await redis.expire(key, 86400)  # 24 hour expiry for safety
            return count
        except Exception as e:
            logger.error(f"Increment concurrent error: {e}")
            return 1

    async def decrement_concurrent(self, tenant_id: str, resource: str) -> int:
        """Decrement concurrent count. Returns new count."""
        key = f"concurrent:{tenant_id}:{resource}"
        try:
            redis = await self._get_redis()
            count = await redis.decr(key)
            if count <= 0:
                await redis.delete(key)
                return 0
            return count
        except Exception as e:
            logger.error(f"Decrement concurrent error: {e}")
            return 0


# Singleton instance
rate_limiter = RateLimiter()
