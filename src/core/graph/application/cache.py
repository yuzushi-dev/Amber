import hashlib
import json
import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

class ExtractionCache:
    """
    Caches Graph Extraction results in Redis to avoid redundant LLM calls.

    Keys are generated based on a hash of the chunk content and relevant configuration.
    """

    def __init__(self, redis_url: str, ttl: int = 60 * 60 * 24 * 7):  # 7 days default
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl

    def _generate_key(self, content: str, tenant_config: dict | None = None) -> str:
        """Generate a unique cache key for the content and config."""
        config_str = json.dumps(tenant_config, sort_keys=True) if tenant_config else ""
        content_hash = hashlib.sha256((content + config_str).encode()).hexdigest()
        return f"extraction_cache:{content_hash}"

    async def get(self, content: str, tenant_config: dict | None = None) -> dict | None:
        """Retrieve cached extraction result if it exists."""
        key = self._generate_key(content, tenant_config)
        try:
            cached = await self.redis.get(key)
            if cached:
                logger.debug(f"Cache hit for key {key}")
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Failed to read from extraction cache: {e}")
        return None

    async def set(self, content: str, result: dict, tenant_config: dict | None = None):
        """Store extraction result in cache."""
        key = self._generate_key(content, tenant_config)
        try:
            await self.redis.set(key, json.dumps(result), ex=self.ttl)
            logger.debug(f"Cached result for key {key}")
        except Exception as e:
            logger.warning(f"Failed to write to extraction cache: {e}")

    async def close(self):
        await self.redis.close()
