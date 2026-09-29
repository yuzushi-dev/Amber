"""
Rate Limiter Core Logic
=======================

Redis-backed sliding window rate limiting.
"""

import logging
import time
from dataclasses import dataclass
from enum import StrEnum

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RateLimitCategory(StrEnum):
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

    def __init__(
        self,
        redis_url: str,
        requests_per_minute: int = 60,
        queries_per_minute: int = 30,
        uploads_per_hour: int = 100,
    ):
        """
        Initialize the rate limiter.

        Args:
            redis_url: Redis connection URL
            requests_per_minute: General rate limit
            queries_per_minute: Query endpoint rate limit
            uploads_per_hour: Upload endpoint rate limit
        """
        self.redis_url = redis_url
        self._redis: Redis | None = None
        self._limits = {
            RateLimitCategory.GENERAL: (requests_per_minute, 60),
            RateLimitCategory.QUERY: (queries_per_minute, 60),
            RateLimitCategory.UPLOAD: (uploads_per_hour, 3600),
        }

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
        return self._limits.get(category, (60, 60))

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

        except Exception:
            # Re-raise so the middleware can decide fail-open vs fail-closed
            raise

# Factory function for creating rate limiter (called by API middleware with settings)
_rate_limiter: RateLimiter | None = None


def get_rate_limiter(
    redis_url: str,
    requests_per_minute: int = 60,
    queries_per_minute: int = 30,
    uploads_per_hour: int = 100,
) -> RateLimiter:
    """Get or create rate limiter singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(
            redis_url, requests_per_minute, queries_per_minute, uploads_per_hour
        )
    return _rate_limiter
