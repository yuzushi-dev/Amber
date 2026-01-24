from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.ingestion.infrastructure.extraction.graph_extractor import GraphExtractor


@pytest.mark.asyncio
async def test_extractor_flow_mocked():
    with patch("src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider") as mock_get, \
         patch("src.shared.kernel.runtime.get_settings") as mock_settings:
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider
        
        mock_settings.return_value.default_llm_model = "gpt-4"
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
    with patch("src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider") as mock_get, \
         patch("src.shared.kernel.runtime.get_settings") as mock_settings:
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider
        
        mock_settings.return_value.default_llm_model = "gpt-4"
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
