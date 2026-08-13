from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.core.ingestion.application import ingestion_service as service_module
from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL, EMBEDDING_MODELS


class FakeDocumentRepository:
    def __init__(self, document):
        self._document = document

    async def get(self, document_id):
        return self._document

    async def update_status(self, document_id, status, old_status=None, attempt_id=None):
        # Track status so validate_transition sees the correct current state
        self._document.status = status
        if attempt_id is not None:
            self._document.processing_attempt_id = attempt_id
        return True

    async def save(self, document):
        return None


class FakeUnitOfWork:
    async def commit(self):
        return None


class FakeStorage:
    def get_file(self, path):
        return b"file-bytes"


class FakeExtractor:
    async def extract(self, **kwargs):
        return SimpleNamespace(
            content="hello world " * 20,  # >100 chars to pass quality gate
            metadata={},
            extractor_used="text",
            confidence=1.0,
            extraction_time_ms=1,
        )


class StubChunker:
    def __init__(self, *args, **kwargs):
        pass

    def chunk(self, content, document_title, metadata=None):
        return [
            SimpleNamespace(
                index=0,
                content="chunk",
                token_count=1,
                start_char=0,
                end_char=5,
                metadata={},
            )
        ]


class StubClassifier:
    async def classify(self, content):
        return SimpleNamespace(value="general")

    async def close(self):
        return None


class StubStrategy:
    name = "stub"


class StubEmbeddingService:
    def __init__(self, *args, **kwargs):
        pass


class StubSparseService:
    def __init__(self, *args, **kwargs):
        pass


class StubChunk:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeEventDispatcher:
    async def emit_state_change(self, event):
        return None


class CaptureFactoryError(Exception):
    pass


class CaptureVectorStoreFactory:
    def __init__(self):
        self.calls = []

    def __call__(self, dimensions, collection_name=None):
        self.calls.append((dimensions, collection_name))
        raise CaptureFactoryError("stop")


def test_milvus_payload_rejects_short_dense_embeddings():
    service = object.__new__(service_module.IngestionService)
    chunks = [SimpleNamespace(id="c1", document_id="doc-1", content="one", metadata_={}),
              SimpleNamespace(id="c2", document_id="doc-1", content="two", metadata_={})]

    with pytest.raises(ValueError, match="[Dd]ense embedding cardinality"):
        service._build_milvus_data(chunks, [[0.1]], [{}, {}], "tenant-1")


def test_milvus_payload_rejects_short_sparse_embeddings():
    service = object.__new__(service_module.IngestionService)
    chunks = [SimpleNamespace(id="c1", document_id="doc-1", content="one", metadata_={}),
              SimpleNamespace(id="c2", document_id="doc-1", content="two", metadata_={})]

    with pytest.raises(ValueError, match="[Ss]parse embedding cardinality"):
        service._build_milvus_data(chunks, [[0.1], [0.2]], [{}], "tenant-1")


def test_milvus_payload_accepts_empty_sparse_vectors_for_each_chunk():
    service = object.__new__(service_module.IngestionService)
    chunks = [SimpleNamespace(id="c1", document_id="doc-1", content="one", metadata_={}),
              SimpleNamespace(id="c2", document_id="doc-1", content="two", metadata_={})]

    payload = service._build_milvus_data(
        chunks, [[0.1], [0.2]], [{}, {}], "tenant-1"
    )

    assert [row["chunk_id"] for row in payload] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_ingestion_uses_active_vector_collection(monkeypatch):
    document = SimpleNamespace(
        id="doc-1",
        tenant_id="tenant-1",
        filename="doc.txt",
        content_hash="hash",
        storage_path="tenant-1/doc-1/doc.txt",
        status=service_module.DocumentStatus.INGESTED,
        source_type="file",
        metadata_={},
        domain=None,
        summary="",
        document_type=None,
        hashtags=[],
        keywords=[],
        chunks=[],
        created_at=datetime.now(UTC),
        error_message=None,
    )

    class TenantRepo:
        async def get(self, tenant_id):
            return SimpleNamespace(config={"active_vector_collection": "amber_custom"})

    factory = CaptureVectorStoreFactory()

    monkeypatch.setattr(service_module, "EmbeddingService", StubEmbeddingService)
    monkeypatch.setattr(service_module, "SemanticChunker", StubChunker)
    monkeypatch.setattr(service_module, "GraphProcessor", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(service_module, "GraphEnricher", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(
        "src.core.ingestion.application.chunking.semantic.SemanticChunker", StubChunker
    )
    monkeypatch.setattr("src.core.ingestion.domain.chunk.Chunk", StubChunk)
    monkeypatch.setattr(
        "src.core.generation.application.intelligence.classifier.DomainClassifier", StubClassifier
    )
    monkeypatch.setattr(
        "src.core.generation.application.intelligence.strategies.get_strategy",
        lambda *_: StubStrategy(),
    )
    monkeypatch.setattr(
        "src.core.retrieval.application.embeddings_service.EmbeddingService", StubEmbeddingService
    )
    monkeypatch.setattr(
        "src.core.retrieval.application.sparse_embeddings_service.SparseEmbeddingService",
        StubSparseService,
    )
    monkeypatch.setattr(
        "src.core.generation.domain.ports.provider_factory.build_provider_factory",
        lambda *a, **k: SimpleNamespace(get_embedding_provider=lambda *a, **k: None),
    )
    monkeypatch.setattr(
        "src.core.generation.domain.ports.provider_factory.get_provider_factory",
        lambda *a, **k: SimpleNamespace(get_embedding_provider=lambda *a, **k: None),
    )

    service = service_module.IngestionService(
        document_repository=FakeDocumentRepository(document),
        tenant_repository=TenantRepo(),
        unit_of_work=FakeUnitOfWork(),
        storage_client=FakeStorage(),
        neo4j_client=SimpleNamespace(),
        vector_store=None,
        content_extractor=FakeExtractor(),
        settings=SimpleNamespace(
            default_embedding_provider="openai",
            default_embedding_model=DEFAULT_EMBEDDING_MODEL["openai"],
            embedding_dimensions=EMBEDDING_MODELS["openai"][DEFAULT_EMBEDDING_MODEL["openai"]][
                "dimensions"
            ],
            openai_api_key="sk-test",
            ollama_base_url=None,
        ),
        task_dispatcher=None,
        event_dispatcher=FakeEventDispatcher(),
        vector_store_factory=factory,
    )

    with pytest.raises(CaptureFactoryError):
        await service.process_document("doc-1")

    assert factory.calls[0][1] == "amber_custom"
