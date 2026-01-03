import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.services.retrieval import RetrievalService, RetrievalResult
from src.api.schemas.query import SearchMode, QueryOptions

@patch("src.core.services.retrieval.ProviderFactory")
@patch("src.core.services.retrieval.MilvusVectorStore")
@patch("src.core.services.retrieval.Neo4jClient")
@patch("src.core.services.retrieval.SemanticCache")
@patch("src.core.services.retrieval.ResultCache")
def test_hybrid_search_orchestration(mock_rc, mock_sc, mock_nc, mock_v, mock_f):
    """Verify that RetrievalService correctly orchestrates hybrid search."""
    service = RetrievalService(openai_api_key="sk-test")
    
    # Mock searchers
    service.vector_searcher.search = AsyncMock(return_value=[])
    # Fix: Also mock the underlying vector_store.search since the fallback mechanism calls it directly
    service.vector_store.search = AsyncMock(return_value=[])
    
    service.entity_searcher.search = AsyncMock(return_value=[])
    service.graph_searcher.search_by_entities = AsyncMock(return_value=[])
    service.graph_traversal.beam_search = AsyncMock(return_value=[])
    
    # Mock result cache (needs to be async)
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock()
    
    # Mock embedding
    service.embedding_service.embed_single = AsyncMock(return_value=[0.1]*1536)
    
    # Mock router to return BASIC
    service.router.route = AsyncMock(return_value="basic")
    
    # Use a dict for options to avoid pydantic issues in mock env
    options = MagicMock()
    options.search_mode = "basic"
    options.use_rewrite = False
    options.use_decomposition = False
    options.use_hyde = False
    
    result = asyncio.run(service.retrieve("test query", tenant_id="test", options=options))
    
    assert isinstance(result, RetrievalResult)
    service.vector_searcher.search.assert_called_once()
    service.entity_searcher.search.assert_called_once()

@patch("src.core.services.retrieval.ProviderFactory")
@patch("src.core.services.retrieval.MilvusVectorStore")
@patch("src.core.services.retrieval.Neo4jClient")
@patch("src.core.services.retrieval.SemanticCache")
@patch("src.core.services.retrieval.ResultCache")
def test_global_search_orchestration(mock_rc, mock_sc, mock_nc, mock_v, mock_f):
    """Verify Global Search mode is called."""
    service = RetrievalService(openai_api_key="sk-test")
    service.global_search.search = AsyncMock(return_value={"answer": "Global Answer", "sources": ["s1"]})
    service.router.route = AsyncMock(return_value="global") # Mode.GLOBAL
    
    options = MagicMock()
    options.search_mode = "global"
    options.use_rewrite = False
    
    result = asyncio.run(service.retrieve("global query", tenant_id="test", options=options))
    
    assert result.chunks[0]["content"] == "Global Answer"
    service.global_search.search.assert_called_once()

@patch("src.core.services.retrieval.ProviderFactory")
@patch("src.core.services.retrieval.MilvusVectorStore")
@patch("src.core.services.retrieval.Neo4jClient")
@patch("src.core.services.retrieval.SemanticCache")
@patch("src.core.services.retrieval.ResultCache")
def test_drift_search_orchestration(mock_rc, mock_sc, mock_nc, mock_v, mock_f):
    """Verify DRIFT Search mode is called."""
    service = RetrievalService(openai_api_key="sk-test")
    service.drift_search.search = AsyncMock(return_value={"candidates": [], "follow_ups": [], "answer": "Drift"})
    service.router.route = AsyncMock(return_value="drift") # Mode.DRIFT
    
    options = MagicMock()
    options.search_mode = "drift"
    options.use_rewrite = False
    
    result = asyncio.run(service.retrieve("drift query", tenant_id="test", options=options))
    
    service.drift_search.search.assert_called_once()
