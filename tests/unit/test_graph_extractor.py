import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.ingestion.infrastructure.extraction.graph_extractor import GraphExtractor
from src.shared.model_registry import DEFAULT_LLM_MODEL


class InMemoryExtractionCache:
    store: dict[str, object] = {}

    def __init__(self, config):
        self.config = config

    @staticmethod
    def build_cache_key(**kwargs):
        return f"{kwargs['tenant_id']}::{kwargs['text']}"

    async def get(self, cache_key: str):
        return self.store.get(cache_key)

    async def set(self, cache_key: str, result):
        self.store[cache_key] = result
        return True


@pytest.mark.asyncio
async def test_extractor_flow_mocked():
    with (
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider"
        ) as mock_get,
        patch("src.shared.kernel.runtime.get_settings") as mock_settings,
    ):
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider

        mock_settings.return_value.default_llm_model = DEFAULT_LLM_MODEL["openai"]
        mock_settings.return_value.db.redis_url = None

        # Mock response Tuple Tuple
        mock_response = MagicMock()
        mock_response.text = '("entity"<|>MORPHEUS<|>PERSON<|>Captain<|>0.9)'
        mock_response.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        mock_response.cost_estimate = 0.001

        mock_provider.generate.return_value = mock_response

        extractor = GraphExtractor(use_gleaning=False)
        result = await extractor.extract("some text")

        assert len(result.entities) == 1
        assert result.entities[0].name == "MORPHEUS"
        assert result.entities[0].type == "PERSON"

        mock_settings.assert_called()


@pytest.mark.asyncio
async def test_extractor_gleaning_mocked():
    with (
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider"
        ) as mock_get,
        patch("src.shared.kernel.runtime.get_settings") as mock_settings,
    ):
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider

        mock_settings.return_value.default_llm_model = DEFAULT_LLM_MODEL["openai"]
        mock_settings.return_value.db.redis_url = None

        # Pass 1 response
        resp1 = MagicMock()
        resp1.text = '("entity"<|>NEO<|>PERSON<|>The One<|>0.9)'
        resp1.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        resp1.cost_estimate = 0.001

        # Pass 2 response (Gleaning)
        resp2 = MagicMock()
        resp2.text = '("entity"<|>TRINITY<|>PERSON<|>Hacker<|>0.9)'
        resp2.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        resp2.cost_estimate = 0.001

        mock_provider.generate.side_effect = [resp1, resp2]

        extractor = GraphExtractor(use_gleaning=True, max_gleaning_steps=1)
        result = await extractor.extract("some text")

        # Should contain both
        names = sorted([e.name for e in result.entities])
        assert names == ["NEO", "TRINITY"]

        mock_settings.assert_called()


@pytest.mark.asyncio
async def test_extractor_cache_hit_skips_llm_call():
    InMemoryExtractionCache.store = {}
    with (
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider"
        ) as mock_get,
        patch("src.shared.kernel.runtime.get_settings") as mock_settings,
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.ExtractionCache",
            InMemoryExtractionCache,
        ),
    ):
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider

        mock_settings.return_value.default_llm_model = DEFAULT_LLM_MODEL["openai"]
        mock_settings.return_value.db.redis_url = "redis://test"

        resp = MagicMock()
        resp.text = '("entity"<|>CACHE_ENTITY<|>CONCEPT<|>Cached once<|>0.9)'
        resp.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        resp.cost_estimate = 0.001
        resp.model = "test-model"
        resp.provider = "test-provider"
        mock_provider.generate.return_value = resp

        extractor = GraphExtractor(use_gleaning=False)
        tenant_config = {
            "graph_sync": {
                "profile": "test_profile",
                "profiles": {
                    "test_profile": {
                        "cache_enabled": True,
                        "cache_ttl_hours": 1,
                        "use_gleaning": False,
                        "max_gleaning_steps": 0,
                    }
                },
            }
        }

        first = await extractor.extract(
            "same text",
            chunk_id="c1",
            track_usage=False,
            tenant_id="tenant-1",
            tenant_config=tenant_config,
        )
        second = await extractor.extract(
            "same text",
            chunk_id="c2",
            track_usage=False,
            tenant_id="tenant-1",
            tenant_config=tenant_config,
        )

        assert len(first.entities) == 1
        assert len(second.entities) == 1
        assert second.usage.cache_hit is True
        assert second.usage.llm_calls == 0
        assert mock_provider.generate.await_count == 1


@pytest.mark.asyncio
async def test_extractor_cache_is_tenant_scoped():
    InMemoryExtractionCache.store = {}
    with (
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider"
        ) as mock_get,
        patch("src.shared.kernel.runtime.get_settings") as mock_settings,
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.ExtractionCache",
            InMemoryExtractionCache,
        ),
    ):
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider

        mock_settings.return_value.default_llm_model = DEFAULT_LLM_MODEL["openai"]
        mock_settings.return_value.db.redis_url = "redis://test"

        resp = MagicMock()
        resp.text = '("entity"<|>TENANT_ENTITY<|>CONCEPT<|>Tenant scoped<|>0.9)'
        resp.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        resp.cost_estimate = 0.001
        resp.model = "test-model"
        resp.provider = "test-provider"
        mock_provider.generate.return_value = resp

        extractor = GraphExtractor(use_gleaning=False)
        tenant_config = {
            "graph_sync": {
                "profile": "test_profile",
                "profiles": {
                    "test_profile": {
                        "cache_enabled": True,
                        "cache_ttl_hours": 1,
                        "use_gleaning": False,
                        "max_gleaning_steps": 0,
                    }
                },
            }
        }

        await extractor.extract(
            "shared text",
            chunk_id="c1",
            track_usage=False,
            tenant_id="tenant-1",
            tenant_config=tenant_config,
        )
        second_tenant = await extractor.extract(
            "shared text",
            chunk_id="c2",
            track_usage=False,
            tenant_id="tenant-2",
            tenant_config=tenant_config,
        )

        assert second_tenant.usage.cache_hit is False
        assert mock_provider.generate.await_count == 2


@pytest.mark.asyncio
async def test_smart_gleaning_skips_when_pass1_yield_is_sufficient():
    with (
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider"
        ) as mock_get,
        patch("src.shared.kernel.runtime.get_settings") as mock_settings,
    ):
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider
        mock_settings.return_value.default_llm_model = DEFAULT_LLM_MODEL["openai"]
        mock_settings.return_value.db.redis_url = None

        pass1 = MagicMock()
        pass1.text = '("entity"<|>NEO<|>PERSON<|>The One<|>0.9)'
        pass1.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        pass1.cost_estimate = 0.001
        pass1.model = "test-model"
        pass1.provider = "test-provider"
        mock_provider.generate.return_value = pass1

        extractor = GraphExtractor(use_gleaning=True, max_gleaning_steps=1)
        tenant_config = {
            "graph_sync": {
                "profile": "smart",
                "profiles": {
                    "smart": {
                        "smart_gleaning_enabled": True,
                        "smart_gleaning_entity_threshold": 1,
                        "smart_gleaning_relationship_threshold": 0,
                        "smart_gleaning_min_chunk_chars": 0,
                    }
                },
            }
        }

        result = await extractor.extract(
            "some text",
            track_usage=False,
            tenant_id="tenant-1",
            tenant_config=tenant_config,
        )
        assert [e.name for e in result.entities] == ["NEO"]
        assert mock_provider.generate.await_count == 1


@pytest.mark.asyncio
async def test_smart_gleaning_runs_when_pass1_yield_is_low():
    with (
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider"
        ) as mock_get,
        patch("src.shared.kernel.runtime.get_settings") as mock_settings,
    ):
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider
        mock_settings.return_value.default_llm_model = DEFAULT_LLM_MODEL["openai"]
        mock_settings.return_value.db.redis_url = None

        pass1 = MagicMock()
        pass1.text = '("entity"<|>NEO<|>PERSON<|>The One<|>0.9)'
        pass1.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        pass1.cost_estimate = 0.001
        pass1.model = "test-model"
        pass1.provider = "test-provider"

        pass2 = MagicMock()
        pass2.text = '("entity"<|>TRINITY<|>PERSON<|>Hacker<|>0.9)'
        pass2.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        pass2.cost_estimate = 0.001
        pass2.model = "test-model"
        pass2.provider = "test-provider"
        mock_provider.generate.side_effect = [pass1, pass2]

        extractor = GraphExtractor(use_gleaning=True, max_gleaning_steps=1)
        tenant_config = {
            "graph_sync": {
                "profile": "smart",
                "profiles": {
                    "smart": {
                        "smart_gleaning_enabled": True,
                        "smart_gleaning_entity_threshold": 2,
                        "smart_gleaning_relationship_threshold": 0,
                        "smart_gleaning_min_chunk_chars": 0,
                    }
                },
            }
        }

        result = await extractor.extract(
            "some text",
            track_usage=False,
            tenant_id="tenant-1",
            tenant_config=tenant_config,
        )
        names = sorted([e.name for e in result.entities])
        assert names == ["NEO", "TRINITY"]
        assert mock_provider.generate.await_count == 2


@pytest.mark.asyncio
async def test_extractor_llm_metrics_include_chunk_progress(caplog):
    caplog.set_level(logging.INFO)

    with (
        patch(
            "src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider"
        ) as mock_get,
        patch("src.shared.kernel.runtime.get_settings") as mock_settings,
    ):
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider
        mock_settings.return_value.default_llm_model = DEFAULT_LLM_MODEL["openai"]
        mock_settings.return_value.db.redis_url = None

        response = MagicMock()
        response.text = '("entity"<|>NEO<|>PERSON<|>The One<|>0.9)'
        response.usage = SimpleNamespace(total_tokens=10, input_tokens=5, output_tokens=5)
        response.cost_estimate = 0.001
        response.model = "test-model"
        response.provider = "test-provider"
        mock_provider.generate.return_value = response

        extractor = GraphExtractor(use_gleaning=False)
        await extractor.extract(
            "some text",
            chunk_id="c2",
            track_usage=False,
            chunk_number=2,
            total_chunks=5,
        )

    llm_metric_logs = [
        r.getMessage()
        for r in caplog.records
        if "graph_extractor_llm_call_metrics" in r.getMessage()
    ]
    assert llm_metric_logs
    payload = json.loads(llm_metric_logs[0].split(" ", 1)[1])
    assert payload["chunk_number"] == 2
    assert payload["total_chunks"] == 5
