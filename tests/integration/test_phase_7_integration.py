import sys
from unittest.mock import MagicMock, AsyncMock

# Manual mock for tiktoken to allow running without pytest
if "tiktoken" not in sys.modules:
    sys.modules["tiktoken"] = MagicMock()

import asyncio
from src.core.services.generation import GenerationService, GenerationConfig
from src.core.providers.base import GenerationResult, TokenUsage

async def test_generation_service_orchestration():
    print("Running test_generation_service_orchestration...")
    # Mock LLM provider
    mock_llm = MagicMock()
    mock_llm.model_name = "gpt-4o"
    
    # Mock generate response
    mock_llm.generate = AsyncMock(return_value=GenerationResult(
        text="The main feature of GraphRAG is its ability to reason over long-range relationships [1].",
        model="gpt-4o",
        provider="openai",
        usage=TokenUsage(input_tokens=100, output_tokens=50),
        cost_estimate=0.001
    ))
    
    service = GenerationService(llm_provider=mock_llm)
    
    candidates = [
        {"content": "GraphRAG integrates vector search with knowledge graphs for deep reasoning.", "chunk_id": "chunk_1", "document_id": "doc_1"}
    ]
    
    result = await service.generate(
        query="What is a key feature of GraphRAG?",
        candidates=candidates
    )
    
    assert "reason over long-range relationships" in result.answer
    assert len(result.sources) == 1
    assert result.sources[0].chunk_id == "chunk_1"
    assert result.tokens_used == 150
    print("test_generation_service_orchestration PASSED")

async def test_generation_service_streaming():
    print("Running test_generation_service_streaming...")
    mock_llm = MagicMock()
    mock_llm.model_name = "gpt-4o"
    
    async def mock_stream(*args, **kwargs):
        tokens = ["Graph", "RAG", " is", " great", " [1]."]
        for t in tokens:
            yield t
            
    mock_llm.generate_stream = mock_stream
    
    service = GenerationService(llm_provider=mock_llm)
    candidates = [{"content": "GraphRAG is a hybrid system.", "chunk_id": "c1"}]
    
    events = []
    async for event in service.generate_stream("Tell me about GraphRAG", candidates):
        events.append(event)
        
    # Check event sequence
    assert events[0]["event"] == "sources"
    assert len(events[0]["data"]) == 1
    
    # Tokens
    token_events = [e for e in events if e["event"] == "token"]
    assert len(token_events) == 5
    assert token_events[0]["data"] == "Graph"
    
    # Done
    assert events[-1]["event"] == "done"
    assert "follow_ups" in events[-1]["data"]
    print("test_generation_service_streaming PASSED")

if __name__ == "__main__":
    async def run_all():
        try:
            await test_generation_service_orchestration()
            await test_generation_service_streaming()
            print("\nALL INTEGRATION TESTS PASSED")
        except Exception as e:
            print(f"\nTEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    asyncio.run(run_all())
