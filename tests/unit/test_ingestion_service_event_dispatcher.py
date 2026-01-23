from typing import Any

import pytest

from src.core.ingestion.application import ingestion_service as service_module


class FakeDocumentRepository:
    def __init__(self) -> None:
        self.saved = []

    async def find_by_content_hash(self, tenant_id: str, content_hash: str):
        return None

    async def save(self, document):
        self.saved.append(document)


class FakeStorage:
    def __init__(self) -> None:
        self.upload_calls = []

    def upload_file(self, object_name: str, data: Any, length: int, content_type: str) -> None:
        self.upload_calls.append((object_name, length, content_type))


class StubChunker:
    def __init__(self, *args, **kwargs) -> None:
        pass


class StubEmbeddingService:
    def __init__(self, *args, **kwargs) -> None:
        pass


class StubGraphProcessor:
    def __init__(self, *args, **kwargs) -> None:
        pass


class StubGraphEnricher:
    def __init__(self, *args, **kwargs) -> None:
        pass


class StubDocument:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeEventDispatcher:
    def __init__(self) -> None:
        self.events = []

    async def emit_state_change(self, event) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_register_document_emits_state_change(monkeypatch):
    monkeypatch.setattr(service_module, "SemanticChunker", StubChunker)
    monkeypatch.setattr(service_module, "EmbeddingService", StubEmbeddingService)
    monkeypatch.setattr(service_module, "GraphProcessor", StubGraphProcessor)
    monkeypatch.setattr(service_module, "GraphEnricher", StubGraphEnricher)
    monkeypatch.setattr(service_module, "Document", StubDocument)
    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", _direct_to_thread)

    dispatcher = FakeEventDispatcher()
    service = service_module.IngestionService(
        document_repository=FakeDocumentRepository(),
        tenant_repository=None,
        unit_of_work=None,
        storage_client=FakeStorage(),
        neo4j_client=object(),
        vector_store=None,
        settings=None,
        task_dispatcher=None,
        event_dispatcher=dispatcher,
    )

    await service.register_document(
        tenant_id="tenant-1",
        filename="doc.txt",
        file_content=b"hello",
        content_type="text/plain",
    )

    assert dispatcher.events
