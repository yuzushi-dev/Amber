import json
import logging
from typing import Any

import redis.asyncio as redis

from src.core.events.ports import StateChangePublisher
from src.shared.kernel.runtime import get_settings

logger = logging.getLogger(__name__)



# a shared client instance to reuse the connection pool
_redis_client: redis.Redis | None = None


def _get_redis_client() -> redis.Redis:
    """Get or create the shared Redis client."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        # Create client with default connection pool
        _redis_client = redis.from_url(settings.db.redis_url)
    return _redis_client


class RedisStatePublisher(StateChangePublisher):
    async def publish(self, payload: dict[str, Any]) -> None:
        channel = payload.get("channel")
        message = payload.get("message", {})
        if not channel:
            raise ValueError("payload missing channel")

        # Use the shared client
        client = _get_redis_client()
        
        # publish returns the number of subscribers, we can ignore it
        # We do NOT close the client here so the pool remains active
        await client.publish(channel, json.dumps(message))
