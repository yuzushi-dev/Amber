import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from src.core.services.tuning import TuningService
from src.core.providers.base import BaseLLMProvider

@pytest.mark.asyncio
async def test_analyze_feedback_positive_ignores():
    """Positive feedback should be ignored."""
    service = TuningService(session_factory=MagicMock())
    service.get_tenant_config = AsyncMock()
    service.update_tenant_weights = AsyncMock()
    
    await service.analyze_feedback_for_tuning("tenant1", "req1", is_positive=True)
    
    service.get_tenant_config.assert_not_called()

@pytest.mark.asyncio
async def test_analyze_feedback_no_details_ignores():
    """Negative feedback without details should be ignored."""
    service = TuningService(session_factory=MagicMock())
    service.get_tenant_config = AsyncMock()
    
    await service.analyze_feedback_for_tuning("tenant1", "req1", is_positive=False)
    
    service.get_tenant_config.assert_not_called()

@pytest.mark.asyncio
async def test_analyze_feedback_retrieval_failure_suggestion():
    """Test that valid retrieval failure feedback triggers analysis and logic."""
    service = TuningService(session_factory=MagicMock())
    
    # Mock LLM provider response
    mock_llm = MagicMock(spec=BaseLLMProvider)
    # Return JSON indicating retrieval failure
    mock_llm.generate = AsyncMock(return_value='{"reason": "RETRIEVAL_FAILURE", "confidence": 0.9, "explanation": "Context missing"}')
    
    with patch("src.core.services.tuning.get_llm_provider", return_value=mock_llm):
        with patch.object(service, "get_tenant_config", new_callable=AsyncMock) as mock_config:
            with patch.object(service, "update_tenant_weights", new_callable=AsyncMock) as mock_update:
                 
                 await service.analyze_feedback_for_tuning(
                     "tenant1", 
                     "req1", 
                     is_positive=False, 
                     comment="Wrong answer", 
                     selected_snippets=["snippet1"]
                 )
                 
                 # Verify LLM was called
                 mock_llm.generate.assert_called_once()
                 
                 # Since we only LOG the action currently, we can't assert update_tenant_weights
                 # But we verify it ran without error and the logic path was taken (coverage)
