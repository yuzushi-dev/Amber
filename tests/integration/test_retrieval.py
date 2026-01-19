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
from src.core.models.document import Document
from src.core.models.chunk import Chunk
from src.core.models.memory import UserFact, ConversationSummary
from src.core.state.machine import DocumentStatus
from src.core.vector_store.milvus import SearchResult

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
        self.mock_vector_store_cls = patch("src.core.services.retrieval.MilvusVectorStore").start()
        self.mock_vector_store = self.mock_vector_store_cls.return_value
        self.mock_vector_store.search = AsyncMock(return_value=[]) 
        self.mock_vector_store.disconnect = AsyncMock()
        
        # Patch EmbeddingService
        self.mock_embed_cls = patch("src.core.services.retrieval.EmbeddingService").start()
        self.mock_embed = self.mock_embed_cls.return_value
        self.mock_embed.embed_single = AsyncMock(return_value=[0.1] * 1536)
        
        # Patch Reranker
        patch("src.core.services.retrieval.BaseRerankerProvider").start()
        
        # Patch Hybrid/Sparse (if used)
        patch("src.core.services.retrieval.SparseEmbeddingService").start()

        # Patch Caches to force MISS (return None)
        # If we don't mock them, they might fail on connection or return truthy mocks
        self.mock_result_cache_cls = patch("src.core.services.retrieval.ResultCache").start()
        self.mock_result_cache = self.mock_result_cache_cls.return_value
        self.mock_result_cache.get = AsyncMock(return_value=None)
        self.mock_result_cache.set = AsyncMock() # Must be awaitable
        
        self.mock_semantic_cache_cls = patch("src.core.services.retrieval.SemanticCache").start()
        self.mock_semantic_cache = self.mock_semantic_cache_cls.return_value
        self.mock_semantic_cache.get = AsyncMock(return_value=None)
        self.mock_semantic_cache.set = AsyncMock() # Must be awaitable

        # Patch LLM Generation AND Retrieval Components
        # We patch at the source (src.core.providers.factory) to catch all usages
        with patch("src.core.providers.factory.ProviderFactory") as MockFactory:
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
                yield "Mocked"
                yield " "
                yield "Stream"
                yield " "
                yield "[DONE]"
            self.mock_llm.generate_stream = mock_stream
            
            MockFactory.return_value.get_llm_provider.return_value = self.mock_llm
            MockFactory.return_value.get_embedding_provider.return_value = MagicMock()
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
            MockFactory.return_value.get_reranker_provider.return_value = self.mock_reranker
            
            # Auth Mocking (Tenant)
            self.tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
            self.user_id = f"user_{uuid.uuid4().hex[:8]}"
            
            # Reset global services in query route to force re-initialization with mocks
            import src.api.routes.query as query_routes
            query_routes._retrieval_service = None
            query_routes._generation_service = None
            query_routes._metrics_collector = None
            
            # Mock Context Graph Writer to prevent Neo4j errors
            self.mock_graph_writer = patch("src.core.graph.context_writer.context_graph_writer").start()
            self.mock_graph_writer.log_turn = AsyncMock()
            
            with patch("src.core.services.api_key_service.ApiKeyService") as MockApiKeyService:
                mock_service = MockApiKeyService.return_value
                mock_key = MagicMock()
                mock_key.name = "Test Key"
                mock_key.scopes = ["admin"]
                
                mock_tenant = MagicMock()
                mock_tenant.id = self.tenant_id
                mock_key.tenants = [mock_tenant]
                
                mock_service.validate_key = AsyncMock(return_value=mock_key)
                
                # Cleanup DB
                async_session = get_session_maker()
                async with async_session() as session:
                    await session.execute(text("DELETE FROM documents WHERE 1=1"))
                    await session.execute(text("DELETE FROM chunks WHERE 1=1"))
                    await session.execute(text("DELETE FROM user_facts WHERE 1=1"))
                    await session.execute(text("DELETE FROM conversation_summaries WHERE 1=1"))
                    await session.commit()
                
                yield

        patch.stopall()

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
        
        # 4. Verify Context Injection via Mock LLM call args
        call_args = self.mock_llm.generate.call_args
        assert call_args is not None
        
        # Args could be (messages, ...) or (prompt, ...) depending on implementation
        # We convert all args to string to search for the fact
        args_str = str(call_args)
        assert secret_fact in args_str, "Context was not injected into LLM prompt"

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
        call_args = self.mock_llm.generate.call_args
        prompt = str(call_args)
        assert "Alice is a Engineer" in prompt
        assert "Alice lives in Paris" in prompt

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
        call_args = self.mock_llm.generate.call_args
        prompt = str(call_args)
        assert fact_text in prompt, "User fact not found in LLM prompt"

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
        
        call_args = self.mock_llm.generate.call_args
        prompt = str(call_args)
        assert summary_text in prompt, "Conversation summary not found in LLM prompt"
    
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
        
        call_args = self.mock_llm.generate.call_args
        assert "Word" in str(call_args)

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
        
        payload = {"query": "Stream me", "stream": True}
        
        async with ac.stream("POST", "/v1/query/stream", json=payload, headers=headers) as resp:
            assert resp.status_code == 200
            events = []
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(line)
            
            assert len(events) > 0
            assert "[DONE]" in events[-1]
