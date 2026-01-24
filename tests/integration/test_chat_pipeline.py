import pytest
import pytest_asyncio
import uuid
import json
import asyncio
import logging
from unittest.mock import MagicMock, AsyncMock, patch
from src.api.schemas.query import SearchMode

# 1. Environment Overrides
# ----------------------------------------------------------------------
import os
import sys
sys.path.append(os.getcwd())

# DATABASE_URL is now handled by the runner or inherits from env
os.environ["DATABASE_URL"] = "postgresql+asyncpg://graphrag:graphrag@127.0.0.1:5433/graphrag_test"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
os.environ["MILVUS_HOST"] = "127.0.0.1"
os.environ["MILVUS_PORT"] = "19530"
os.environ["OPENAI_API_KEY"] = "sk-test-key-mock"

from httpx import AsyncClient, ASGITransport
from sqlalchemy import text 
from src.core.generation.infrastructure.providers.base import GenerationResult as LLMGenerationResult, TokenUsage
from src.core.generation.application.generation_service import GenerationResult as AppGenerationResult

# ----------------------------------------------------------------------
# 2. Application Imports
# ----------------------------------------------------------------------
from src.api.main import app
from src.core.database.session import get_session_maker, configure_database, reset_engine
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.chunk import Chunk
from src.core.generation.domain.memory_models import UserFact, ConversationSummary
from src.core.state.machine import DocumentStatus
from src.core.retrieval.infrastructure.vector_store.milvus import SearchResult

# ----------------------------------------------------------------------
# 3. Test Class
# ----------------------------------------------------------------------
class TestChatPipelineComprehensive:
    """
    Comprehensive integration tests for Chat logic.
    Mocking external AI services to focus on pipeline logic.
    """

    @pytest_asyncio.fixture(autouse=True)
    async def setup_dependencies(self):
        """Mock all external dependencies securely."""
        
        # 0. Provider Factory Patch (Global)
        self.mock_factory = MagicMock()
        self.mock_factory.get_embedding_provider.return_value = AsyncMock()
        self.mock_factory.get_llm_provider.return_value = AsyncMock()
        self.mock_factory.get_reranker_provider.return_value = AsyncMock()
        
        self.patch_factory_builder = patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder", return_value=self.mock_factory).start()

        # 0.1 Configure Database explicitly
        reset_engine()
        configure_database(
            database_url=os.environ["DATABASE_URL"],
            pool_size=5,
            max_overflow=10
        )

        # 1. Vector Store
        self.mock_vector_store_cls = patch("src.core.retrieval.infrastructure.vector_store.milvus.MilvusVectorStore").start()
        self.mock_vector_store = self.mock_vector_store_cls.return_value
        self.mock_vector_store.search = AsyncMock(return_value=[]) 
        self.mock_vector_store.disconnect = AsyncMock()
        
        # 2. Embedding
        from src.core.retrieval.application.embeddings_service import EmbeddingService
        self.mock_embed_service = MagicMock(spec=EmbeddingService)
        self.mock_embed_service.embed_single = AsyncMock(return_value=[0.1]*1536)
        
        # 3. Reranker
        from src.core.generation.infrastructure.providers.base import BaseRerankerProvider
        self.mock_reranker = MagicMock(spec=BaseRerankerProvider)

        # 3.1 Caches (Must be patched BEFORE RetrievalService init)
        self.mock_result_cache_cls = patch("src.core.retrieval.application.retrieval_service.ResultCache").start()
        self.mock_result_cache = self.mock_result_cache_cls.return_value
        self.mock_result_cache.get = AsyncMock(return_value=None)
        self.mock_result_cache.set = AsyncMock()
        
        self.mock_semantic_cache_cls = patch("src.core.retrieval.application.retrieval_service.SemanticCache").start()
        self.mock_semantic_cache_cls.return_value.get = AsyncMock(return_value=None)
        self.mock_semantic_cache_cls.return_value.set = AsyncMock()
        
        # 4. Retrieval Service
        # 4. Retrieval Service
        from src.core.retrieval.application.retrieval_service import RetrievalService
        from src.core.generation.infrastructure.providers.base import ProviderTier
        mock_config = MagicMock(enable_reranking=False, enable_hybrid=False, top_k=5)
        mock_config.llm_tier = ProviderTier.ECONOMY
        self.mock_neo4j = AsyncMock() # Neo4j client mock
        
        from src.core.ingestion.domain.ports.document_repository import DocumentRepository
        self.mock_doc_repo = MagicMock(spec=DocumentRepository)
        self.mock_doc_repo.get_chunks = AsyncMock(return_value=[])

        self.retrieval_service = RetrievalService(
            document_repository=self.mock_doc_repo,
            vector_store=self.mock_vector_store,
            neo4j_client=self.mock_neo4j,
            openai_api_key="test",
            config=mock_config
        )
        self.retrieval_service.embedding_service = self.mock_embed_service
        self.retrieval_service.reranker = None # Disable for simplicity
        


        # 6. LLM
        self.mock_llm = AsyncMock()
        self.mock_llm.model_name = "mock-model"
        self.mock_llm.generate.return_value = LLMGenerationResult(
            text="I am a mocked LLM response.",
            model="mock-model",
            provider="mock-provider",
            usage=TokenUsage(input_tokens=5, output_tokens=5),
            cost_estimate=0.0
        )
        # Streaming mock
        async def mock_stream(*args, **kwargs):
            yield "Mocked"
            yield " "
            yield "Stream"
            yield " "
            yield "[DONE]"
        self.mock_llm.generate_stream = mock_stream
        
        # 7. Generation Service
        from src.core.generation.application.generation_service import GenerationService
        self.generation_service = GenerationService(llm_provider=self.mock_llm)
        
        # 8. Patch Composition Root Builders
        self.patch_retrieval_builder = patch("src.amber_platform.composition_root.build_retrieval_service", return_value=self.retrieval_service).start()
        self.patch_generation_builder = patch("src.amber_platform.composition_root.build_generation_service", return_value=self.generation_service).start()
        
        self.mock_metrics_collector = MagicMock()
        self.mock_metrics_collector.track_query.return_value.__aenter__.return_value = MagicMock()
        self.patch_metrics_builder = patch("src.amber_platform.composition_root.build_metrics_collector", return_value=self.mock_metrics_collector).start()

        self.tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
        self.user_id = f"user_{uuid.uuid4().hex[:8]}"

        # 8. Reset Singleton Services in Query Route
        import src.api.routes.query as query_routes
        query_routes._retrieval_service = None
        query_routes._generation_service = None
        query_routes._metrics_collector = None
        
        # 9. Graph Writer & Context
        patch("src.core.graph.application.context_writer.context_graph_writer").start()
        
        # 10. Auth / ApiKeyService
        self.mock_api_key_service_cls = patch("src.core.admin_ops.application.api_key_service.ApiKeyService").start()
        mock_auth_service = self.mock_api_key_service_cls.return_value
        
        mock_key = MagicMock()
        mock_key.id = "test-key-id"
        mock_key.name = "Test Key"
        mock_key.scopes = ["admin"]
        mock_tenant = MagicMock()
        mock_tenant.id = self.tenant_id
        mock_key.tenants = [mock_tenant]
        
        mock_auth_service.validate_key = AsyncMock(return_value=mock_key)

        # 11. Database Cleanup
        async_session = get_session_maker()
        async with async_session() as session:
            await session.execute(text("DELETE FROM chunks WHERE 1=1"))
            await session.execute(text("DELETE FROM documents WHERE 1=1"))
            await session.execute(text("DELETE FROM user_facts WHERE 1=1"))
            await session.execute(text("DELETE FROM conversation_summaries WHERE 1=1"))
            await session.commit()
            
        yield

        patch.stopall()

    @pytest_asyncio.fixture
    async def client(self):
        headers = {
            "X-API-Key": "test-key", 
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, headers

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    async def _seed_document_and_chunk(self, content: str, filename: str = "seed.txt"):
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"
        chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
        
        async_session = get_session_maker()
        async with async_session() as session:
            doc = Document(
                id=doc_id,
                tenant_id=self.tenant_id,
                filename=filename,
                content_hash=uuid.uuid4().hex,
                storage_path="path",
                status=DocumentStatus.READY
            )
            session.add(doc)
            chunk = Chunk(
                id=chunk_id,
                tenant_id=self.tenant_id,
                document_id=doc_id,
                index=0,
                content=content[:1000],
                tokens=len(content.split()),
                embedding_status="completed",
                metadata_={}
            )
            session.add(chunk)
            await session.commit()
            
        return doc_id, chunk_id, content

    # ------------------------------------------------------------------
    # TESTS
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_basic_rag(self, client):
        ac, headers = client
        secret = "The code is 1234."
        doc_id, chunk_id, content = await self._seed_document_and_chunk(secret)
        
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=chunk_id, document_id=doc_id, tenant_id=self.tenant_id, score=0.9, metadata={"content": content})
        ]
        
        await ac.post("/v1/query", json={"query": "Code?", "user_id": self.user_id}, headers=headers)
        
        call_args = str(self.mock_llm.generate.call_args)
        assert secret in call_args

    @pytest.mark.asyncio
    async def test_multi_doc_synthesis(self, client):
        ac, headers = client
        d1, c1, t1 = await self._seed_document_and_chunk("Part A: Fire.", "a.txt")
        d2, c2, t2 = await self._seed_document_and_chunk("Part B: Water.", "b.txt")
        
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=c1, document_id=d1, tenant_id=self.tenant_id, score=0.9, metadata={"content": t1}),
            SearchResult(chunk_id=c2, document_id=d2, tenant_id=self.tenant_id, score=0.9, metadata={"content": t2}),
        ]
        
        await ac.post("/v1/query", json={"query": "Combine?", "user_id": self.user_id}, headers=headers)
        
        call_args = str(self.mock_llm.generate.call_args)
        assert "Part A: Fire" in call_args
        assert "Part B: Water" in call_args

    @pytest.mark.asyncio
    async def test_context_window(self, client):
        ac, headers = client
        huge_content = "Word " * 5000 
        d1, c1, _ = await self._seed_document_and_chunk(huge_content)
        
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=c1, document_id=d1, tenant_id=self.tenant_id, score=0.9, metadata={"content": huge_content})
        ]
        
        await ac.post("/v1/query", json={"query": "Test", "user_id": self.user_id}, headers=headers)
        call_args = str(self.mock_llm.generate.call_args)
        assert "Word" in call_args

    @pytest.mark.asyncio
    async def test_history(self, client):
        ac, headers = client
        summary_text = "User previously asked about Project Alpha."
        
        async_session = get_session_maker()
        async with async_session() as session:
            s = ConversationSummary(
                id=str(uuid.uuid4()),
                tenant_id=self.tenant_id, 
                user_id=self.user_id,
                title="Previous Chat",
                summary=summary_text
            )
            session.add(s)
            await session.commit()
            
        d_dummy, c_dummy, _ = await self._seed_document_and_chunk("Generic")
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=c_dummy, document_id=d_dummy, tenant_id=self.tenant_id, score=0.5, metadata={"content": "Generic content."})
        ]
        
        await ac.post("/v1/query", json={"query": "What project?", "user_id": self.user_id}, headers=headers)
        call_args = str(self.mock_llm.generate.call_args)
        assert summary_text in call_args

    @pytest.mark.asyncio
    async def test_fallback(self, client):
        ac, headers = client
        self.mock_vector_store.search.return_value = [] 
        resp = await ac.post("/v1/query", json={"query": "Unknowable?", "user_id": self.user_id}, headers=headers)
        assert resp.status_code == 200
        assert "couldn't find" in resp.text

    @pytest.mark.asyncio
    async def test_streaming(self, client):
        ac, headers = client
        d_dummy, c_dummy, _ = await self._seed_document_and_chunk("Streamable")
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=c_dummy, document_id=d_dummy, tenant_id=self.tenant_id, score=0.5, metadata={"content": "Streamable content."})
        ]
        async with ac.stream("POST", "/v1/query/stream", json={"query": "Stream", "stream": True, "user_id": self.user_id}, headers=headers) as resp:
            assert resp.status_code == 200
            events = [line async for line in resp.aiter_lines() if line.startswith("data: ")]
            assert len(events) >= 1
            assert "[DONE]" in events[-1]

    @pytest.mark.asyncio
    async def test_user_facts(self, client):
        ac, headers = client
        fact = "User is a Python Developer."
        async_session = get_session_maker()
        async with async_session() as session:
            f = UserFact(id=str(uuid.uuid4()), tenant_id=self.tenant_id, user_id=self.user_id, content=fact, importance=1.0)
            session.add(f)
            await session.commit()
            
        d_dummy, c_dummy, _ = await self._seed_document_and_chunk("Generic")
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=c_dummy, document_id=d_dummy, tenant_id=self.tenant_id, score=0.5, metadata={"content": "Generic content."})
        ]
        
        await ac.post("/v1/query", json={"query": "Who am I?", "user_id": self.user_id}, headers=headers)
        call_args = str(self.mock_llm.generate.call_args)
        assert "Python Developer" in call_args

    @pytest.mark.asyncio
    async def test_conversation_summaries(self, client):
        ac, headers = client
        summary = "User likes Star Wars."
        async_session = get_session_maker()
        async with async_session() as session:
            s = ConversationSummary(id=str(uuid.uuid4()), tenant_id=self.tenant_id, user_id=self.user_id, title="Movie Chat", summary=summary)
            session.add(s)
            await session.commit()
            
        d_dummy, c_dummy, _ = await self._seed_document_and_chunk("Generic")
        self.mock_vector_store.search.return_value = [
            SearchResult(chunk_id=c_dummy, document_id=d_dummy, tenant_id=self.tenant_id, score=0.5, metadata={"content": "Generic context."})
        ]
        
        await ac.post("/v1/query", json={"query": "Movies?", "user_id": self.user_id}, headers=headers)
        call_args = str(self.mock_llm.generate.call_args)
        assert "Star Wars" in call_args
