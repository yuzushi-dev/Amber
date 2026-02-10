import json
import logging
from typing import Any

import redis.asyncio as redis

from src.core.events.ports import StateChangePublisher
from src.shared.kernel.runtime import get_settings

logger = logging.getLogger(__name__)


class RedisStatePublisher(StateChangePublisher):
    async def publish(self, payload: dict[str, Any]) -> None:
        channel = payload.get("channel")
        message = payload.get("message", {})
        if not channel:
            raise ValueError("payload missing channel")

        settings = get_settings()
        client = redis.from_url(settings.db.redis_url)
        try:
            await client.publish(channel, json.dumps(message))
        finally:
            await client.aclose()
