import pytest
from unittest.mock import AsyncMock, patch
from src.core.extraction.graph_extractor import GraphExtractor

@pytest.mark.asyncio
async def test_extractor_parse_valid():
    extractor = GraphExtractor(use_gleaning=False)
    
    # Valid JSON
    json_text = """
    {
        "entities": [{"name": "Neo", "type": "PERSON", "description": "The One"}],
        "relationships": []
    }
    """
    result = extractor._parse_result(json_text)
    assert len(result.entities) == 1
    assert result.entities[0].name == "Neo"
    assert result.entities[0].type == "PERSON"

@pytest.mark.asyncio
async def test_extractor_parse_markdown():
    extractor = GraphExtractor(use_gleaning=False)
    
    # JSON in Markdown code block
    json_text = """
    ```json
    {
        "entities": [{"name": "Trinity", "type": "PERSON", "description": "Hacker"}],
        "relationships": []
    }
    ```
    """
    result = extractor._parse_result(json_text)
    assert len(result.entities) == 1
    assert result.entities[0].name == "Trinity"

@pytest.mark.asyncio
async def test_extractor_flow_mocked():
    with patch("src.core.extraction.graph_extractor.get_llm_provider") as mock_get:
        mock_provider = AsyncMock()
        mock_get.return_value = mock_provider
        
        # Mock response
        mock_response = AsyncMock()
        mock_response.text = '{"entities": [{"name": "Morpheus", "type": "PERSON", "description": "Captain"}], "relationships": []}'
        mock_provider.generate.return_value = mock_response
        
        extractor = GraphExtractor(use_gleaning=False)
        result = await extractor.extract("some text")
        
        assert len(result.entities) == 1
        assert result.entities[0].name == "Morpheus"
        
        # Verify provider was called with Economy tier (or generally called)
        # Note: In implementation we called get_llm_provider(tier=ProviderTier.ECONOMY)
        # We can check args if we want strict verification
        # mock_get.assert_called_with(tier=ProviderTier.ECONOMY) # Need to import ProviderTier to check this
