"""Unit tests for Part B of the ingestion-dedup-and-ready-filter fix: the
recovery sweep gains an INGESTED branch (documents stuck before any worker
ever picked them up) and a batch LIMIT so the first sweep after deploy does
not dispatch all stuck documents (up to 67 on prod) in one burst.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.state.machine import DocumentStatus


def _mock_document(doc_id: str, status: DocumentStatus, filename: str = "doc.pdf"):
    # status is kept as the real DocumentStatus enum member (not `.value`):
    # the real `documents.status` column is `Mapped[DocumentStatus]`, so
    # `document.status.value` (used by _publish_recovery_status) must work.
    doc = MagicMock()
    doc.id = doc_id
    doc.tenant_id = "tenant-1"
    doc.filename = filename
    doc.status = status
    doc.updated_at = datetime.now(UTC)
    doc.error_message = None
    return doc


@pytest.mark.asyncio
async def test_recovery_sweep_requeues_ingested_without_status_reset():
    """A document stuck in INGESTED (never picked up by a worker) must be
    requeued for reprocessing, and its status must stay INGESTED - not reset
    to FAILED, and with no other reset needed since it is already in the
    state process_document's optimistic guard expects."""
    from src.workers.recovery import recover_stale_documents

    doc = _mock_document("doc_ingested_1", DocumentStatus.INGESTED)

    mock_result_stale = MagicMock()
    mock_result_stale.scalars.return_value.all.return_value = [doc]

    mock_result_chunks = MagicMock()
    mock_result_chunks.scalars.return_value.first.return_value = None  # no chunks yet

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[mock_result_stale, mock_result_chunks])
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.workers.recovery.create_async_engine") as mock_engine,
        patch("src.workers.recovery.sessionmaker") as mock_sessionmaker,
        patch("src.workers.recovery._publish_recovery_status"),
        patch("src.core.database.session.configure_worker_session", new_callable=AsyncMock),
        patch("src.workers.tasks.process_document") as mock_process_document,
    ):
        mock_sessionmaker.return_value.return_value = mock_session
        mock_engine.return_value.dispose = AsyncMock()

        result = await recover_stale_documents()

    assert result["recovered"] == 1
    assert result["failed"] == 0
    # The whole point of the fix: status is untouched (still INGESTED), not FAILED.
    assert doc.status == DocumentStatus.INGESTED.value
    mock_process_document.delay.assert_called_once_with("doc_ingested_1", "tenant-1")


@pytest.mark.asyncio
async def test_recovery_sweep_respects_batch_limit():
    """Even if 100 documents are stale, a single sweep execution must not
    dispatch more than 50 - otherwise the first sweep after deploy could
    fire off up to 67 full reprocessing pipelines in one burst."""
    from src.workers.recovery import recover_stale_documents

    docs = [_mock_document(f"doc_{i}", DocumentStatus.INGESTED) for i in range(100)]

    executed_statements = []

    async def _fake_execute(stmt):
        executed_statements.append(stmt)
        if len(executed_statements) == 1:
            # The stale-document query itself. This fake stands in for
            # Postgres and actually HONORS the statement's LIMIT clause (if
            # any) when slicing the 100 available rows - unlike a plain
            # canned return value, this makes the test fail if the LIMIT is
            # ever removed from the query (all 100 would come back).
            limit_clause = getattr(stmt, "_limit_clause", None)
            limit_value = limit_clause.value if limit_clause is not None else None
            rows = docs[:limit_value] if limit_value is not None else docs
            result = MagicMock()
            result.scalars.return_value.all.return_value = rows
            return result
        # Per-document "has chunks?" check.
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        return result

    mock_session = AsyncMock()
    mock_session.execute = _fake_execute
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.workers.recovery.create_async_engine") as mock_engine,
        patch("src.workers.recovery.sessionmaker") as mock_sessionmaker,
        patch("src.workers.recovery._publish_recovery_status"),
        patch("src.core.database.session.configure_worker_session", new_callable=AsyncMock),
        patch("src.workers.tasks.process_document") as mock_process_document,
    ):
        mock_sessionmaker.return_value.return_value = mock_session
        mock_engine.return_value.dispose = AsyncMock()

        await recover_stale_documents()

    # Structural check: the stale-document query itself must carry LIMIT 50.
    stale_stmt = executed_statements[0]
    assert stale_stmt._limit_clause is not None, "stale document query must have a LIMIT"
    assert stale_stmt._limit_clause.value == 50

    # Behavioral check: with the fake DB honoring that LIMIT, out of 100
    # available stale documents only 50 are fetched and therefore only 50
    # get dispatched in this single sweep run.
    assert mock_process_document.delay.call_count == 50
