"""Keep retry metadata until every external store has been cleaned."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.ingestion.application.use_cases_documents import (
    DeleteDocumentRequest,
    DeleteDocumentUseCase,
)


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize("failure", ["graph", "vectors", "disconnect", "storage", None])
async def test_cleanup_failure_preserves_row_and_can_be_retried(failure):
    events = []
    document = SimpleNamespace(
        processing_attempt_id=None, tenant_id="tenant-1", storage_path="tenant-1/current"
    )
    results = [
        Mock(scalars=Mock(return_value=Mock(first=Mock(return_value=document)))),
        Mock(
            scalars=Mock(
                return_value=Mock(all=Mock(return_value=["tenant-1/old", "tenant-1/current"]))
            )
        ),
    ]
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=results * 2),
        delete=AsyncMock(side_effect=lambda _: events.append("postgres-delete")),
        commit=AsyncMock(side_effect=lambda: events.append("postgres-commit")),
    )

    async def graph_delete(*args):
        events.append("graph")
        if failure == "graph":
            raise RuntimeError("graph failed")
        return []

    async def vector_delete(*args):
        events.append("vectors")
        if failure == "vectors":
            raise RuntimeError("vectors failed")

    async def disconnect():
        if failure == "disconnect":
            raise RuntimeError("disconnect failed")

    def storage_delete(path):
        events.append(path)
        if failure == "storage":
            raise RuntimeError("storage failed")

    graph = SimpleNamespace(
        execute_read=AsyncMock(), execute_write=AsyncMock(side_effect=graph_delete)
    )
    vectors = SimpleNamespace(
        delete_by_document=AsyncMock(side_effect=vector_delete),
        disconnect=AsyncMock(side_effect=disconnect),
    )
    storage = SimpleNamespace(delete_file=Mock(side_effect=storage_delete))
    use_case = DeleteDocumentUseCase(session, storage, graph, lambda _: vectors)
    request = DeleteDocumentRequest(document_id="doc-1", tenant_id="tenant-1")

    if failure:
        with pytest.raises(RuntimeError, match="failed"):
            await use_case.execute(request)
        session.delete.assert_not_awaited()
        session.commit.assert_not_awaited()
        failure = None

    await use_case.execute(request)
    graph.execute_read.assert_not_awaited()
    assert "FOR UPDATE" in str(session.execute.await_args_list[0].args[0])
    session.delete.assert_awaited_once_with(document)
    session.commit.assert_awaited_once()
    assert events[-4:] == ["tenant-1/current", "tenant-1/old", "postgres-delete", "postgres-commit"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_active_processing_blocks_cleanup():
    from src.core.ingestion.application.use_cases_documents import DocumentDeletionConflict

    document = SimpleNamespace(processing_attempt_id="attempt")
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=Mock(scalars=Mock(return_value=Mock(first=Mock(return_value=document))))
        ),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )
    graph = SimpleNamespace(execute_write=AsyncMock())
    storage = Mock()
    factory = Mock()
    use_case = DeleteDocumentUseCase(session, storage, graph, factory)
    with pytest.raises(DocumentDeletionConflict):
        await use_case.execute(DeleteDocumentRequest(document_id="doc", tenant_id="tenant"))
    graph.execute_write.assert_not_awaited()
    factory.assert_not_called()
    storage.delete_file.assert_not_called()
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize("busy", [False, True])
async def test_folder_is_retained_when_document_cleanup_fails(monkeypatch, busy):
    import sys

    from fastapi import HTTPException

    from src.api.routes.folders import delete_folder
    from src.core.ingestion.application.use_cases_documents import DocumentDeletionConflict

    folder = SimpleNamespace(id="folder")
    document = SimpleNamespace(id="doc")
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                Mock(scalar_one_or_none=Mock(return_value=folder)),
                Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[document])))),
            ]
        ),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.amber_platform.composition_root",
        SimpleNamespace(
            platform=SimpleNamespace(minio_client=Mock(), neo4j_client=Mock()),
            build_vector_store_factory=Mock(return_value=Mock()),
        ),
    )
    error = DocumentDeletionConflict("busy") if busy else RuntimeError("cleanup failed")
    monkeypatch.setattr(DeleteDocumentUseCase, "execute", AsyncMock(side_effect=error))
    with pytest.raises(HTTPException if busy else RuntimeError) as exc:
        await delete_folder("folder", delete_contents=True, session=session, tenant_id="tenant")
    if busy:
        assert exc.value.status_code == 409
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()
