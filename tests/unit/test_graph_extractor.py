from unittest.mock import AsyncMock, patch

import pytest

from src.core.extraction.graph_extractor import GraphExtractor


@pytest.mark.asyncio
async def test_extractor_flow_mocked():
    with patch("src.core.extraction.graph_extractor.get_llm_provider") as mock_get:
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider

        # Mock response Tuple Tuple
        mock_response = AsyncMock()
        mock_response.text = '("entity"<|>MORPHEUS<|>PERSON<|>Captain<|>0.9)'
        mock_provider.generate.return_value = mock_response

        extractor = GraphExtractor(use_gleaning=False)
        result = await extractor.extract("some text")

        assert len(result.entities) == 1
        assert result.entities[0].name == "MORPHEUS"
        assert result.entities[0].type == "PERSON"

@pytest.mark.asyncio
async def test_extractor_gleaning_mocked():
    with patch("src.core.extraction.graph_extractor.get_llm_provider") as mock_get:
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider

        # Pass 1 response
        resp1 = AsyncMock()
        resp1.text = '("entity"<|>NEO<|>PERSON<|>The One<|>0.9)'

        # Pass 2 response (Gleaning)
        resp2 = AsyncMock()
        resp2.text = '("entity"<|>TRINITY<|>PERSON<|>Hacker<|>0.9)'

        mock_provider.generate.side_effect = [resp1, resp2]

        extractor = GraphExtractor(use_gleaning=True, max_gleaning_steps=1)
        result = await extractor.extract("some text")

        # Should contain both
        names = sorted([e.name for e in result.entities])
        assert names == ["NEO", "TRINITY"]
