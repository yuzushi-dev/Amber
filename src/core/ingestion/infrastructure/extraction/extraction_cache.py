import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from src.core.generation.application.prompts.entity_extraction import ExtractionResult

logger = logging.getLogger(__name__)


def _get_redis():
    try:
        import redis.asyncio as redis

        return redis
    except ImportError as e:
        raise ImportError(
            "redis package is required for extraction cache. Install with: pip install redis>=5.0.0"
        ) from e


@dataclass
class ExtractionCacheConfig:
    redis_url: str
    ttl_seconds: int = 7 * 24 * 3600
    key_prefix: str = "graph_extraction_cache"
    enabled: bool = False


class ExtractionCache:
    """Redis-backed cache for graph extraction results."""

    EXTRACTOR_VERSION = "graph_extractor_v2"

    def __init__(self, config: ExtractionCacheConfig):
        self.config = config
        self._client = None

    async def _get_client(self):
        if self._client is None:
            redis = _get_redis()
            self._client = redis.from_url(self.config.redis_url, decode_responses=True)
        return self._client

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def build_cache_key(
        cls,
        *,
        tenant_id: str,
        text: str,
        prompt: str,
        ontology: dict[str, Any],
        model: str,
        temperature: float,
        seed: int | None,
        gleaning_mode: str,
    ) -> str:
        chunk_hash = cls._sha256(text)
        prompt_hash = cls._sha256(prompt)
        ontology_hash = cls._sha256(json.dumps(ontology, sort_keys=True))

        payload = {
            "tenant_id": tenant_id,
            "chunk_hash": chunk_hash,
            "prompt_hash": prompt_hash,
            "ontology_hash": ontology_hash,
            "model": model,
            "temperature": temperature,
            "seed": seed,
            "gleaning_mode": gleaning_mode,
            "extractor_version": cls.EXTRACTOR_VERSION,
        }
        digest = cls._sha256(json.dumps(payload, sort_keys=True))
        return f"{cls.EXTRACTOR_VERSION}:{digest}"

    def _redis_key(self, cache_key: str) -> str:
        return f"{self.config.key_prefix}:{cache_key}"

    async def get(self, cache_key: str) -> ExtractionResult | None:
        if not self.config.enabled:
            return None

        try:
            client = await self._get_client()
            data = await client.get(self._redis_key(cache_key))
            if not data:
                return None
            parsed = json.loads(data)
            return ExtractionResult.model_validate(parsed)
        except Exception as e:
            logger.warning("Extraction cache get failed: %s", e)
            return None

    async def set(self, cache_key: str, result: ExtractionResult) -> bool:
        if not self.config.enabled:
            return False

        try:
            client = await self._get_client()
            payload = result.model_dump()
            await client.setex(
                self._redis_key(cache_key),
                self.config.ttl_seconds,
                json.dumps(payload, sort_keys=True),
            )
            return True
        except Exception as e:
            logger.warning("Extraction cache set failed: %s", e)
            return False

