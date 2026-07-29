"""The recovery sweep must not touch a document another worker replica is
processing right now.

The boot-time sweep used to run with no age threshold, justified by "nothing is
in-flight at startup".  That held with one worker; docker-compose.yml declares
`replicas: 3`, so the worker_ready signal fires once per replica and a single
restarting replica would sweep the other two replicas' live work: EXTRACTING and
CLASSIFYING documents marked FAILED, EMBEDDING and GRAPH_SYNC reset to INGESTED
and requeued while the original task is still running, with the requeued run
executing the destructive pre-ingest cleanup concurrently with the original run's
writes.

These tests fail if the threshold goes back to 0, at either the default or the
worker_ready call site, and if the blanket community-lock flush comes back.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.state.machine import DocumentStatus


def _mock_document(doc_id: str, status: DocumentStatus, age: timedelta):
    doc = MagicMock()
    doc.id = doc_id
    doc.tenant_id = "tenant-1"
    doc.filename = f"{doc_id}.pdf"
    doc.status = status
    doc.updated_at = datetime.now(UTC) - age
    doc.error_message = None
    return doc


def _cutoff_from(stmt):
    """Read the updated_at cutoff out of the stale-document query.

    Returns None when the query carries no age filter at all — which is exactly
    the regression these tests guard against, so the fake DB below then returns
    every row and the behavioural assertions fail.
    """
    for clause in stmt._where_criteria:
        left = getattr(clause, "left", None)
        right = getattr(clause, "right", None)
        if getattr(left, "name", None) == "updated_at" and hasattr(right, "value"):
            return right.value
    return None


@pytest.mark.asyncio
async def test_sweep_skips_documents_another_replica_is_processing():
    from src.workers.recovery import STALE_MIN_AGE_MINUTES, recover_stale_documents

    assert STALE_MIN_AGE_MINUTES > 0, "a zero floor lets a sweep reset live work"

    # Mid-pipeline on another replica: touched a minute ago.
    inflight = _mock_document("doc_inflight", DocumentStatus.EXTRACTING, timedelta(minutes=1))
    # Genuinely abandoned: untouched for two hours.
    stuck = _mock_document("doc_stuck", DocumentStatus.INGESTED, timedelta(hours=2))

    executed = []

    async def _fake_execute(stmt):
        executed.append(stmt)
        if len(executed) == 1:
            # Stand in for Postgres and actually HONOR the age predicate, so
            # removing it from the query changes the rows this test sees.
            cutoff = _cutoff_from(stmt)
            rows = [inflight, stuck]
            if cutoff is not None:
                rows = [d for d in rows if d.updated_at < cutoff]
            result = MagicMock()
            result.scalars.return_value.all.return_value = rows
            return result
        result = MagicMock()
        result.scalars.return_value.first.return_value = None  # no chunks
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

        result = await recover_stale_documents()

    # Structural: the query must carry an age predicate at all.
    assert _cutoff_from(executed[0]) is not None, "stale-document query must filter on updated_at"

    # Behavioural: the in-flight document was never seen, so it was not failed.
    assert inflight.status == DocumentStatus.EXTRACTING, (
        "a document updated a minute ago belongs to a live worker; "
        "marking it FAILED strands its chunks behind the non-READY blocklist"
    )
    assert result["total"] == 1
    assert result["failed"] == 0
    mock_process_document.delay.assert_called_once_with("doc_stuck", "tenant-1")


def test_worker_ready_sweep_uses_the_safety_floor():
    """The worker_ready signal must not override the floor back to 0.

    Patches the async recovery entry point rather than run_recovery_sync, so the
    default that reaches it is the real one from the real call chain.
    """
    from src.workers.celery_app import on_worker_ready
    from src.workers.recovery import STALE_MIN_AGE_MINUTES

    seen: list[int] = []

    async def _capture(min_age_minutes: int):
        seen.append(min_age_minutes)
        return {"recovered": 0, "failed": 0, "total": 0}

    with patch("src.workers.recovery.recover_stale_documents", _capture):
        on_worker_ready()

    assert seen == [STALE_MIN_AGE_MINUTES], (
        f"worker_ready swept with min_age_minutes={seen}; "
        f"expected the {STALE_MIN_AGE_MINUTES}-minute floor"
    )


def test_worker_ready_does_not_flush_community_locks():
    """Community locks carry a 2h TTL and expire on their own.

    A blanket flush at boot releases the locks the other replicas are holding,
    letting two workers run community detection for the same tenant at once.
    Constructing a Redis client here at all is the regression.
    """
    from src.workers.celery_app import on_worker_ready

    async def _noop(min_age_minutes: int):
        return {"recovered": 0, "failed": 0, "total": 0}

    with (
        patch("src.workers.recovery.recover_stale_documents", _noop),
        patch("redis.Redis.from_url") as mock_redis,
    ):
        on_worker_ready()

    mock_redis.assert_not_called()
