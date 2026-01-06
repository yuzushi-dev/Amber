"""
Cache Decorators
================

Simple caching utilities for API endpoints using Redis.
"""

import functools
import json
import logging
import os
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _get_redis():
    """Get redis module with lazy loading."""
    try:
        import redis.asyncio as redis
        return redis
    except ImportError as e:
        raise ImportError("redis package is required. Install with: pip install redis>=5.0.0") from e


async def get_from_cache(key: str) -> dict | None:
    """
    Get value from Redis cache.

    Args:
        key: Cache key

    Returns:
        Parsed JSON dict or None if not found
    """
    try:
        redis = _get_redis()
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = await redis.from_url(redis_url, decode_responses=True)

        value = await r.get(key)
        await r.close()

        if value:
            logger.debug(f"Cache HIT: {key}")
            return json.loads(value)

        logger.debug(f"Cache MISS: {key}")
        return None

    except Exception as e:
        logger.warning(f"Cache read failed for key '{key}': {e}")
        return None


async def set_cache(key: str, value: dict, ttl: int = 60) -> bool:
    """
    Set value in Redis cache with TTL.

    Args:
        key: Cache key
        value: Dict to cache (will be JSON serialized)
        ttl: Time to live in seconds (default: 60)

    Returns:
        True if cached successfully
    """
    try:
        redis = _get_redis()
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = await redis.from_url(redis_url, decode_responses=True)

        await r.setex(key, ttl, json.dumps(value))
        await r.close()

        logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
        return True

    except Exception as e:
        logger.warning(f"Cache write failed for key '{key}': {e}")
        return False


async def delete_cache(key: str) -> bool:
    """
    Delete value from Redis cache.

    Args:
        key: Cache key

    Returns:
        True if deleted successfully
    """
    try:
        redis = _get_redis()
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = await redis.from_url(redis_url, decode_responses=True)

        await r.delete(key)
        await r.close()

        logger.debug(f"Cache DELETE: {key}")
        return True

    except Exception as e:
        logger.warning(f"Cache delete failed for key '{key}': {e}")
        return False


def cached(ttl: int = 60, key_prefix: str = ""):
    """
    Decorator to cache async function results in Redis.

    Args:
        ttl: Time to live in seconds (default: 60)
        key_prefix: Prefix for cache key

    Usage:
        @cached(ttl=60, key_prefix="admin:stats")
        async def get_stats():
            return expensive_computation()

    Example:
        @cached(ttl=30, key_prefix="curation")
        async def get_curation_stats(tenant_id: str):
            # ... expensive queries ...
            return {"total": 100, "pending": 50}
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from function name + args
            key_parts = [key_prefix, func.__name__] if key_prefix else [func.__name__]

            # Add positional args to key
            if args:
                key_parts.extend(str(a) for a in args)

            # Add keyword args to key (sorted for consistency)
            if kwargs:
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))

            cache_key = ":".join(key_parts)

            # Try to get from cache
            cached_value = await get_from_cache(cache_key)
            if cached_value is not None:
                return cached_value

            # Cache miss - execute function
            result = await func(*args, **kwargs)

            # Store in cache (convert to dict if needed)
            if hasattr(result, 'dict'):
                # Pydantic model
                cache_data = result.dict()
            elif hasattr(result, '__dict__'):
                # Regular object
                cache_data = result.__dict__
            elif isinstance(result, dict):
                # Already a dict
                cache_data = result
            else:
                # Primitive type or unknown - wrap it
                cache_data = {"value": result}

            await set_cache(cache_key, cache_data, ttl=ttl)

            return result

        return wrapper
    return decorator
