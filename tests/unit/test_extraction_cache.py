import json

import pytest

from src.core.generation.application.prompts.entity_extraction import (
    ExtractedEntity,
    ExtractionResult,
)
from src.core.ingestion.infrastructure.extraction.extraction_cache import (
    ExtractionCache,
    ExtractionCacheConfig,
)


class _FakeRedisClient:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, _ttl: int, value: str):
        self.store[key] = value


class _FakeRedisModule:
    def __init__(self, client: _FakeRedisClient):
        self.client = client

    def from_url(self, _url: str, decode_responses: bool = True):
        assert decode_responses is True
        return self.client


@pytest.mark.asyncio
async def test_extraction_cache_roundtrip(monkeypatch):
    fake_client = _FakeRedisClient()
    fake_module = _FakeRedisModule(fake_client)

    monkeypatch.setattr(
        "src.core.ingestion.infrastructure.extraction.extraction_cache._get_redis",
        lambda: fake_module,
    )

    cache = ExtractionCache(
        ExtractionCacheConfig(redis_url="redis://test", ttl_seconds=3600, enabled=True)
    )
    key = "k1"
    payload = ExtractionResult(
        entities=[ExtractedEntity(name="NEO", type="PERSON", description="The One")],
        relationships=[],
    )

    await cache.set(key, payload)
    loaded = await cache.get(key)

    assert loaded is not None
    assert len(loaded.entities) == 1
    assert loaded.entities[0].name == "NEO"


def test_extraction_cache_key_includes_tenant_scope():
    common = {
        "text": "same text",
        "prompt": "same prompt",
        "ontology": {"entity_types": ["CONCEPT"], "relationship_suggestions": ["RELATED_TO"]},
        "model": "m1",
        "temperature": 0.0,
        "seed": 42,
        "gleaning_mode": "use=true;max=1;smart=false;e=2;r=1;chars=250",
    }
    key_t1 = ExtractionCache.build_cache_key(tenant_id="tenant-1", **common)
    key_t2 = ExtractionCache.build_cache_key(tenant_id="tenant-2", **common)

    assert key_t1 != key_t2
    assert "graph_extractor_v2:" in key_t1
    assert "graph_extractor_v2:" in key_t2
