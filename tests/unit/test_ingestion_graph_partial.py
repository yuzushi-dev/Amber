import json
from types import SimpleNamespace

import pytest

from src.core.graph.application.processor import GraphProcessingResult
from src.core.ingestion.application.ingestion_service import IngestionService
from src.core.state.machine import DocumentStatus


class _Repository:
    def __init__(self) -> None:
        self.status_updates = []
        self.saved = []

    async def update_status(self, document_id, status, old_status=None):
        self.status_updates.append((document_id, status, old_status))
        return True

    async def save(self, document):
        self.saved.append(document)


class _UnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self):
        self.commits += 1


class _Events:
    def __init__(self) -> None:
        self.events = []

    async def emit_state_change(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_partial_graph_sync_is_reviewable_and_keeps_successful_work():
    repository = _Repository()
    unit_of_work = _UnitOfWork()
    events = _Events()
    service = object.__new__(IngestionService)
    service.document_repository = repository
    service.unit_of_work = unit_of_work
    service.event_dispatcher = events

    document = SimpleNamespace(
        id="doc-1",
        tenant_id="tenant-1",
        status=DocumentStatus.GRAPH_SYNC,
        metadata_={},
        error_message=None,
    )
    result = GraphProcessingResult(
        total_chunks=25,
        failed_chunk_ids=[f"chunk-{index}" for index in range(25)],
    )

    await service._mark_graph_sync_partial(document, result)

    assert document.status == DocumentStatus.NEEDS_REVIEW
    assert repository.status_updates == [
        ("doc-1", DocumentStatus.NEEDS_REVIEW, DocumentStatus.GRAPH_SYNC)
    ]
    assert unit_of_work.commits == 1
    assert repository.saved == [document]

    error_data = json.loads(document.error_message)
    assert error_data["code"] == "graph_sync_partial_failure"
    assert error_data["failed_chunk_count"] == 25
    assert len(error_data["failed_chunk_ids"]) == 20
    assert document.metadata_["graphSyncStatus"] == "partial"
    assert events.events[0].new_status == DocumentStatus.NEEDS_REVIEW
