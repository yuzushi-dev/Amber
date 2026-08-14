"""
Integration tests for ProvisioningService atomicity.

Regression coverage for the gap found in review after PR #128 was opened:
`_copy_docs_and_chunks` used to `commit()` every `_BATCH` (50) documents,
with no job-wide transaction and no `IntegrityError` handling. With the new
`uq_documents_tenant_content_hash` constraint, a job that dies partway
through (e.g. a naive retry that re-copies documents already present in the
target tenant from a previous partial run) would leave batches 1..N-1
permanently committed — a half-provisioned target tenant that requires
manual DB cleanup to recover from.

`provision()` now stages every Postgres write (embedding-config stamp,
folders, documents, chunks) on a single session/transaction via `flush()`
only, and commits once — in the caller — after the whole job succeeds. On
any exception it rolls back everything the job has staged. This test drives
that path end-to-end against a real Postgres instance and asserts that a
mid-job failure leaves ZERO new rows behind.
"""

import uuid

import pytest
from sqlalchemy import select, text

from src.core.admin_ops.application.provisioning_service import ProvisioningService
import src.core.admin_ops.application.provisioning_service as provisioning_service_module
from src.core.admin_ops.domain.provisioning_job import ProvisioningJob
from src.core.database.session import configure_worker_session, get_session_maker
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant


async def _configure(session, tenant_id: str = "") -> None:
    """Run as a privileged worker session (bypasses RLS), matching how the
    real Celery task configures its session (see provisioning_tasks.py)."""
    await configure_worker_session(session, tenant_id)


def _make_source_doc(tenant_id: str, title: str, n_chunks: int = 1) -> Document:
    doc = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        filename=f"{title}.md",
        content_hash=uuid.uuid4().hex,
        storage_path=f"{tenant_id}/{title}.md",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={},
        keywords=[],
        hashtags=[],
    )
    return doc


@pytest.mark.asyncio
async def test_mid_job_integrity_error_leaves_zero_rows_committed(monkeypatch):
    """Batch 2 of 3 hits `uq_documents_tenant_content_hash` (simulating a
    retry that re-copies a document already provisioned into the target
    tenant by a previous, partially-failed run). The whole job must roll
    back — zero new Document/Chunk rows in the target tenant, not a
    partially-committed state.
    """
    source_tenant_id = f"prov-src-{uuid.uuid4().hex[:8]}"
    target_tenant_id = f"prov-tgt-{uuid.uuid4().hex[:8]}"

    session_maker = get_session_maker()

    # ── Setup: source docs + a pre-existing target doc that will collide ── #
    async with session_maker() as setup_session:
        await _configure(setup_session)

        setup_session.add(Tenant(id=source_tenant_id, name="prov-source", config={}))
        setup_session.add(Tenant(id=target_tenant_id, name="prov-target", config={}))
        await setup_session.flush()

        # 5 READY source documents -> with _BATCH=2 that's batches [2, 2, 1].
        source_docs = [_make_source_doc(source_tenant_id, f"doc-{i}") for i in range(5)]
        for doc in source_docs:
            setup_session.add(doc)
            setup_session.add(
                Chunk(
                    id=str(uuid.uuid4()),
                    tenant_id=source_tenant_id,
                    document_id=doc.id,
                    index=0,
                    content="hello world",
                    tokens=2,
                    metadata_={},
                )
            )

        # Pre-existing document in the TARGET tenant whose content_hash
        # collides with the 3rd source doc (batch index 2 -> falls in the
        # 2nd flush batch of [2, 2, 1]). Mirrors a previous partial run (or
        # a duplicate provisioning request) that already copied this one.
        colliding_doc = Document(
            id=str(uuid.uuid4()),
            tenant_id=target_tenant_id,
            filename="already-there.md",
            content_hash=source_docs[2].content_hash,
            storage_path=f"{target_tenant_id}/already-there.md",
            status=DocumentStatus.READY,
            source_type="upload",
            metadata_={},
            keywords=[],
            hashtags=[],
        )
        setup_session.add(colliding_doc)

        job = ProvisioningJob(
            id=str(uuid.uuid4()),
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            document_ids=None,
            folder_ids=None,
            include_graph=False,
        )
        setup_session.add(job)
        await setup_session.commit()

    # ── Enable the legacy provisioning policy gate for this test ── #
    from src.shared.kernel.runtime import get_settings

    monkeypatch.setattr(get_settings(), "enable_tenant_provisioning", True)

    # ── Shrink the batch size so 5 docs -> 3 batches, collision in batch 2 ── #
    monkeypatch.setattr(provisioning_service_module, "_BATCH", 2)

    # ── Run provisioning on a FRESH session, exactly like the real worker ── #
    job_session = session_maker()
    await _configure(job_session)

    service = ProvisioningService(
        session=job_session,
        vector_store_factory=lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Milvus copy should never run — Postgres copy must fail first")
        ),
        neo4j_client=None,
    )

    from sqlalchemy.exc import IntegrityError

    # Everything from here on must run inside try/finally: whatever happens
    # (assertion failure included), the seed/target rows created above must
    # never linger in the shared test database.
    try:
        try:
            with pytest.raises(IntegrityError):
                await service.provision(job.id)
        finally:
            # Mirrors `async with async_session() as session:` exiting on
            # exception in provisioning_tasks._provision_async.
            await job_session.close()

        # ── Verify: zero new rows in the target tenant, only the seed doc ── #
        async with session_maker() as verify_session:
            await _configure(verify_session)

            docs = (
                await verify_session.execute(
                    select(Document).where(Document.tenant_id == target_tenant_id)
                )
            ).scalars().all()
            assert [d.id for d in docs] == [colliding_doc.id], (
                "Expected only the pre-existing colliding document in the target "
                "tenant; a partial commit would leave batch-1 documents behind too."
            )

            chunks = (
                await verify_session.execute(
                    select(Chunk).where(Chunk.tenant_id == target_tenant_id)
                )
            ).scalars().all()
            assert chunks == [], "Expected zero chunks copied into the target tenant."

            # Job row itself: the RUNNING commit in the real Celery task
            # happens on a separate transaction *before* provision() is
            # called, so it's unaffected by this rollback. We didn't perform
            # that step here (we call provision() directly), so the job
            # stays at its initial PENDING status — provision() only
            # mutates it via progress callbacks the caller provides, none
            # passed in this test.
            refreshed_job = await verify_session.get(ProvisioningJob, job.id)
            assert refreshed_job is not None
    finally:
        # ── Cleanup: always runs, even if an assertion above failed ── #
        async with session_maker() as cleanup_session:
            await _configure(cleanup_session)
            await cleanup_session.execute(
                text("DELETE FROM chunks WHERE tenant_id IN (:s, :t)"),
                {"s": source_tenant_id, "t": target_tenant_id},
            )
            await cleanup_session.execute(
                text("DELETE FROM documents WHERE tenant_id IN (:s, :t)"),
                {"s": source_tenant_id, "t": target_tenant_id},
            )
            await cleanup_session.execute(
                text("DELETE FROM provisioning_jobs WHERE id = :j"), {"j": job.id}
            )
            await cleanup_session.execute(
                text("DELETE FROM tenants WHERE id IN (:s, :t)"),
                {"s": source_tenant_id, "t": target_tenant_id},
            )
            await cleanup_session.commit()
