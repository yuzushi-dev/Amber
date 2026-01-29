import pytest
import pytest_asyncio
import uuid
import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# ----------------------------------------------------------------------
# 1. Environment Overrides (Must be before app imports)
# ----------------------------------------------------------------------
import os
import sys
sys.path.append(os.getcwd())

os.environ["DATABASE_URL"] = "postgresql+asyncpg://graphrag:graphrag@localhost:5433/graphrag"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["MILVUS_HOST"] = "localhost"
os.environ["MILVUS_PORT"] = "19530"
os.environ["OPENAI_API_KEY"] = "sk-test-key"

from httpx import AsyncClient, ASGITransport
from sqlalchemy import text 

# ----------------------------------------------------------------------
# 2. Application Imports
# ----------------------------------------------------------------------
from src.api.main import app
from src.core.database.session import get_session_maker
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.chunk import Chunk
from src.core.generation.domain.memory_models import UserFact, ConversationSummary
from src.core.state.machine import DocumentStatus
from src.core.retrieval.infrastructure.vector_store.milvus import SearchResult

# ----------------------------------------------------------------------
# 3. Test Class
# ----------------------------------------------------------------------
class TestChatRetrievalDirectSeeding:
    """
    Integration tests for Chat using Direct Database Seeding & Mocked Retrieval.
    
    Strategy:
    1. Bypass Ingestion: Insert Document/Chunk records directly into Postgres.
    2. Mock Vector Store: Patch `MilvusVectorStore.search` to return seeded chunks.
    3. Verify Generation: Check if the LLM uses the context.
    """

    @pytest_asyncio.fixture(autouse=True)
    async def setup_dependencies(self):
        """
        Setup mocks for External Services.
        """
        # Patch MilvusVectorStore
        self.mock_vector_store_cls = patch("src.core.retrieval.infrastructure.vector_store.milvus.MilvusVectorStore").start()
        self.mock_vector_store = self.mock_vector_store_cls.return_value
        self.mock_vector_store.search = AsyncMock(return_value=[]) 
        self.mock_vector_store.disconnect = AsyncMock()
        
        # Patch EmbeddingService
        self.mock_embed_cls = patch("src.core.retrieval.application.retrieval_service.EmbeddingService").start()
        self.mock_embed = self.mock_embed_cls.return_value
        self.mock_embed.embed_single = AsyncMock(return_value=[0.1] * 1536)
        
        # Patch Hybrid/Sparse (if used)
        patch("src.core.retrieval.application.retrieval_service.SparseEmbeddingService").start()

        # Patch Caches to force MISS (return None)
        # If we don't mock them, they might fail on connection or return truthy mocks
        self.mock_result_cache_cls = patch("src.core.retrieval.application.retrieval_service.ResultCache").start()
        self.mock_result_cache = self.mock_result_cache_cls.return_value
        self.mock_result_cache.get = AsyncMock(return_value=None)
        self.mock_result_cache.set = AsyncMock() # Must be awaitable
        
        self.mock_semantic_cache_cls = patch("src.core.retrieval.application.retrieval_service.SemanticCache").start()
        self.mock_semantic_cache = self.mock_semantic_cache_cls.return_value
        self.mock_semantic_cache.get = AsyncMock(return_value=None)
        self.mock_semantic_cache.set = AsyncMock() # Must be awaitable

        # Use explicit setters instead of patching ports (more reliable for global state)
        from src.core.generation.domain.ports.provider_factory import set_provider_factory, set_provider_factory_builder
        
        factory = MagicMock()
        set_provider_factory(factory)
        # Also set the builder, because GenerationService calls it if API keys are detected
        set_provider_factory_builder(lambda **kwargs: factory)

        self.mock_llm = AsyncMock()
        # Default response
        self.mock_llm.generate.return_value = MagicMock(
            text="I am a mocked LLM response.",
            model="mock-model",
            provider="mock-provider",
            usage=MagicMock(total_tokens=10, input_tokens=5, output_tokens=5),
            cost_estimate=0.0
        )
        # Make sure generate_stream is an async generator
        async def mock_stream(*args, **kwargs):
            yield {"event": "status", "data": "Generating..."}
            yield {"event": "token", "data": "Mocked"}
            yield {"event": "token", "data": " "}
            yield {"event": "token", "data": "Stream"}
            yield {"event": "done", "data": {"model": "mock-model"}}
        self.mock_llm.generate_stream = mock_stream
        
        factory.get_llm_provider.return_value = self.mock_llm
        factory.get_embedding_provider.return_value = MagicMock()
        # Setup Reranker Mock
        self.mock_reranker = AsyncMock()
        async def pass_through_rerank(query, texts):
            # Return result structure expected by RetrievalService
            # Use MagicMock for the result object
            result = MagicMock()
            # Create results list where each item corresponds to input text index
            # Ensure high score to prevent filtering
            result.results = [
                MagicMock(index=i, score=0.99) 
                for i in range(len(texts))
            ]
            return result
        self.mock_reranker.rerank = AsyncMock(side_effect=pass_through_rerank)
        factory.get_reranker_provider.return_value = self.mock_reranker
        
        # Auth Mocking (Tenant)
        self.tenant_id = "integration_test_tenant"
        self.user_id = f"user_{uuid.uuid4().hex[:8]}"
        
        # Reset global services in query route to force re-initialization with mocks
        # (This is still good to keep)
        import src.api.routes.query as query_routes
        query_routes._retrieval_service = None
        query_routes._generation_service = None
        query_routes._metrics_collector = None
        
        # Mock Context Graph Writer if needed
        self.mock_graph_writer = patch("src.core.graph.application.context_writer.context_graph_writer").start()
        self.mock_graph_writer.log_turn = AsyncMock()
        
        # We must clean up set_provider_factory after test
        try:
            with patch("src.core.admin_ops.application.api_key_service.ApiKeyService") as MockApiKeyService:
                mock_service = MockApiKeyService.return_value
                mock_key = MagicMock()
                mock_key.id = "test-key-id"
                mock_key.name = "Test Key"
                mock_key.scopes = ["admin"]
                
                mock_tenant = MagicMock()
                mock_tenant.id = self.tenant_id
                mock_key.tenants = [mock_tenant]
                
                mock_service.validate_key = AsyncMock(return_value=mock_key)
                
                # Cleanup DB
                async_session = get_session_maker()
                async with async_session() as session:
                    await session.execute(text(f"DELETE FROM chunks WHERE tenant_id = '{self.tenant_id}'"))
                    await session.execute(text(f"DELETE FROM documents WHERE tenant_id = '{self.tenant_id}'"))
                    await session.execute(text(f"DELETE FROM user_facts WHERE tenant_id = '{self.tenant_id}'"))
                    await session.execute(text(f"DELETE FROM conversation_summaries WHERE tenant_id = '{self.tenant_id}'"))
                    await session.commit()
                
                yield

        finally:
            set_provider_factory(None)
            set_provider_factory_builder(None)
            patch.stopall()
            
            # Reset global dependencies to prevent loop leakage across tests
            import src.api.middleware.rate_limit as rate_limit_module
            rate_limit_module._rate_limiter = None

            import src.api.deps as deps_module
            deps_module._async_session_maker = None
            
            # Close DB
            from src.core.database.session import close_database
            await close_database()

            # Allow background tasks (like log_turn) to finish/cancel to avoid "Task pending" errors
            await asyncio.sleep(0.1)

    @pytest_asyncio.fixture
    async def client(self):
        """Async Client with Auth Headers."""
        headers = {
            "X-API-Key": "test-key", 
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, headers

    # Util for Async Generator
    async def _async_generator(self, items):
        for item in items:
            yield item
            await asyncio.sleep(0.01)

    # ------------------------------------------------------------------
    # Helper: Direct Seeding
    # ------------------------------------------------------------------
    async def _seed_document_and_chunk(self, content: str, filename: str = "seed.txt"):
        """Insert a document and a single chunk into DB."""
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"
        chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
        
        async_session = get_session_maker()
        async with async_session() as session:
            # Document
            doc = Document(
                id=doc_id,
                tenant_id=self.tenant_id,
                filename=filename,
                content_hash=uuid.uuid4().hex,
                storage_path="path",
                status=DocumentStatus.READY
            )
            session.add(doc)
            
            # Chunk
            chunk = Chunk(
                id=chunk_id,
                tenant_id=self.tenant_id,
                document_id=doc_id,
                index=0,
                content=content[:1000],  # Truncate for DB entry if needed
                tokens=len(content.split()),
                embedding_status="completed",
                metadata_={}
            )
            session.add(chunk)
            await session.commit()
            
        return doc_id, chunk_id, content

    # ------------------------------------------------------------------
    # Test Cases
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_basic_rag_seeded(self, client):
        """1. Basic RAG: Seed -> Mock Retrieval -> Verify context usage."""
        ac, headers = client
        
        # 1. Seed DB
        secret_fact = f"The secret password is {uuid.uuid4().hex[:6]}"
        doc_id, chunk_id, content = await self._seed_document_and_chunk(secret_fact)
        
        # 2. Mock Vector Search returning this chunk
        mock_result = SearchResult(
            chunk_id=chunk_id,
            document_id=doc_id,
            tenant_id=self.tenant_id,
            score=0.95,
            metadata={"content": content} 
        )
        self.mock_vector_store.search.return_value = [mock_result]
        
        # 3. Query
        payload = {
            "query": "What is the secret?",
            "conversation_id": str(uuid.uuid4()),
            "user_id": self.user_id
        }
        resp = await ac.post("/v1/query", json=payload, headers=headers)
        assert resp.status_code == 200
        
        # 4. Verify Context Injection via Mock LLM calls
        # Note: The LLM might be called multiple times (e.g. for Memory Extraction).
        # We need to find the call that corresponds to Answer Generation.
        
        found_fact = False
        all_calls = self.mock_llm.generate.call_args_list
        for call in all_calls:
            args_str = str(call)
            if secret_fact in args_str:
                found_fact = True
                break
                
        assert found_fact, f"Context '{secret_fact}' was not injected into any LLM prompt. Calls: {len(all_calls)}"

    @pytest.mark.asyncio
    async def test_multi_doc_synthesis(self, client):
        """2. Multi-Doc: Seed 2 Chunks -> Mock Retrieval -> Verify both in context."""
        ac, headers = client
        
        # Seed
        _, c1_id, t1 = await self._seed_document_and_chunk("Alice is a Engineer.", "alice.txt")
        _, c2_id, t2 = await self._seed_document_and_chunk("Alice lives in Paris.", "city.txt")
        
        # Mock Search returning BOTH
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=c1_id, document_id="d1", tenant_id=self.tenant_id, score=0.9, metadata={"content": t1}),
            SearchResult(chunk_id=c2_id, document_id="d2", tenant_id=self.tenant_id, score=0.9, metadata={"content": t2}),
        ]
        
        # Query
        payload = {"query": "Tell me about Alice.", "user_id": self.user_id}
        await ac.post("/v1/query", json=payload, headers=headers)
        
        # Verify Context
        found_context = False
        for call in self.mock_llm.generate.call_args_list:
            prompt = str(call)
            if "Alice is a Engineer" in prompt and "Alice lives in Paris" in prompt:
                found_context = True
                break
        assert found_context, "Merged context from multiple docs not found in LLM prompt"

    @pytest.mark.asyncio
    async def test_user_facts_injection(self, client):
        """7. User Facts: Seed Fact -> Verify injection."""
        ac, headers = client
        
        # Seed Fact
        fact_text = "User prefers concise answers."
        async_session = get_session_maker()
        async with async_session() as session:
            fact = UserFact(
                id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                content=fact_text,
                importance=1.0
            )
            session.add(fact)
            await session.commit()
            
        # Mock Search (return dummy chunk to allow generation to proceed)
        # If no chunks are found, query route returns early without calling LLM
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id="dummy", document_id="d0", tenant_id=self.tenant_id, score=0.5, metadata={"content": "Generic context."})
        ]
        
        # Query
        payload = {"query": "Hello", "user_id": self.user_id}
        await ac.post("/v1/query", json=payload, headers=headers)
        
        # Verify Context
        # Note: User facts might be injected via MemoryService calling get_user_facts
        # This test verifies that the system pulls them.
        # Verify Context
        # Note: User facts might be injected via MemoryService calling get_user_facts
        # This test verifies that the system pulls them.
        found_fact = False
        for call in self.mock_llm.generate.call_args_list:
            if fact_text in str(call):
                found_fact = True
                break
        assert found_fact, "User fact not found in LLM prompt"

    @pytest.mark.asyncio
    async def test_conversation_summaries(self, client):
        """8. Summaries: Seed Summary -> Verify injection."""
        ac, headers = client
        
        summary_text = "Previously discussed Project Apollo."
        async_session = get_session_maker()
        async with async_session() as session:
            summ = ConversationSummary(
                id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                title="Historical Chat",
                summary=summary_text
            )
            session.add(summ)
            await session.commit()
            
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id="dummy", document_id="d0", tenant_id=self.tenant_id, score=0.5, metadata={"content": "Generic context."})
        ]
        
        payload = {"query": "Update on that project?", "user_id": self.user_id}
        await ac.post("/v1/query", json=payload, headers=headers)
        
        call_args_list = self.mock_llm.generate.call_args_list
        found_summary = any(summary_text in str(call) for call in call_args_list)
        assert found_summary, "Conversation summary not found in LLM prompt"
    
    @pytest.mark.asyncio
    async def test_context_window_seed(self, client):
        """3. Context Window: Seed large chunk -> Check handling."""
        ac, headers = client
        
        large_content = "Word " * 1000
        _, c_id, _ = await self._seed_document_and_chunk(large_content, "large.txt")
        
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=c_id, document_id="l1", tenant_id=self.tenant_id, score=0.9, metadata={"content": large_content})
        ]
        
        # Ensure it doesn't crash on tokenization
        await ac.post("/v1/query", json={"query": "test"}, headers=headers)
        
        await ac.post("/v1/query", json={"query": "test"}, headers=headers)
        
        found_word = any("Word" in str(call) for call in self.mock_llm.generate.call_args_list)
        assert found_word, "Large context (Word...Word) not found in prompt"

    @pytest.mark.asyncio
    async def test_fallback_behavior(self, client):
        """5. Fallback: No hits -> Verify valid response."""
        ac, headers = client
        self.mock_vector_store.search.return_value = []
        
        resp = await ac.post("/v1/query", json={"query": "Unknown?"}, headers=headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_streaming_sse(self, client):
        """6. Streaming: Verify SSE chunks."""
        ac, headers = client
        
        # Mock successful retrieval so pipeline proceeds to generation
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id="c_stream", document_id="d_stream", tenant_id=self.tenant_id, score=0.9, metadata={"content": "Streaming context."})
        ]
        
        payload = {"query": "Stream me", "stream": True}
        
        async with ac.stream("POST", "/v1/query/stream", json=payload, headers=headers) as resp:
            assert resp.status_code == 200
            events = []
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(line)
            
            assert len(events) > 0
            assert "[DONE]" in events[-1]
