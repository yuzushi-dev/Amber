import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.getcwd())

from unittest.mock import MagicMock, AsyncMock

# Configure logging first
from src.core.admin_ops.infrastructure.observability.logging import configure_logging
configure_logging(log_level="INFO", json_format=False)

import structlog
logger = structlog.get_logger()

# Initialize settings for GenerationService
from src.shared.kernel.runtime import configure_settings
from unittest.mock import MagicMock

# Create dummy settings
dummy_settings = MagicMock()
dummy_settings.openai_api_key = "sk-dummy"
dummy_settings.anthropic_api_key = "sk-ant-dummy"
dummy_settings.default_llm_provider = "openai"
dummy_settings.default_llm_model = "gpt-4o"
configure_settings(dummy_settings)

async def test_ollama_logging():
    logger.info("--- Testing Ollama Provider Logging ---")
    from src.core.generation.infrastructure.providers.ollama import OllamaLLMProvider
    from src.core.generation.infrastructure.providers.base import ProviderConfig

    # Mock the internal client
    provider = OllamaLLMProvider(config=ProviderConfig(base_url="http://mock:11434"))
    provider._client = MagicMock()
    
    # Mock chat completion response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This is a mocked Ollama response."
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 20
    mock_response.id = "mock-id"
    
    provider._client.chat.completions.create = AsyncMock(return_value=mock_response)

    # Call generate 
    logger.info("Calling generate()...")
    result = await provider.generate(prompt="Test prompt")
    logger.info("Generate finished.", result_preview=result.text)

async def test_generation_service_logging():
    logger.info("\n--- Testing Generation Service Logging ---")
    from src.core.generation.application.generation_service import GenerationService, GenerationConfig
    
    # Mock LLM provider
    mock_llm = MagicMock()
    mock_llm.model_name = "mock-model"
    mock_llm.provider_name = "mock-provider"
    
    mock_result = MagicMock()
    mock_result.text = "This is the final answer with a citation [1]."
    mock_result.model = "mock-model"
    mock_result.provider = "mock-provider"
    mock_result.latency_ms = 100.0
    mock_result.usage.input_tokens = 50
    mock_result.usage.output_tokens = 50
    mock_result.cost_estimate = 0.0
    
    mock_llm.generate = AsyncMock(return_value=mock_result)

    service = GenerationService(llm_provider=mock_llm)
    
    # Mock candidates
    candidates = [{"content": "Source content", "chunk_id": "1", "document_id": "doc1", "score": 0.9}]
    
    logger.info("Calling service.generate()...")
    result = await service.generate(query="Test query", candidates=candidates)
    logger.info("Service generate finished.", answer_len=len(result.answer))

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.run_until_complete(test_ollama_logging())
    loop.run_until_complete(test_generation_service_logging())
    loop.close()
