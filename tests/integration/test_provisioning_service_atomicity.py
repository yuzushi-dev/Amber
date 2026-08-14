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

import asyncio
import uuid

import pytest
from sqlalchemy import select, text

import src.core.admin_ops.application.provisioning_service as provisioning_service_module
from src.core.admin_ops.application.provisioning_service import ProvisioningService
from src.core.admin_ops.domain.provisioning_job import ProvisioningJob
from src.core.database.session import configure_worker_session, get_session_maker
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document
from src.core.state.machine import DocumentStatus
from src.core.tenants.application.active_vector_collection import resolve_active_vector_collection
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


# --------------------------------------------------------------------------- #
# Regression coverage for the second review round on PR #128:
#
# - `_copy_vectors` / `_copy_graph` used to swallow their own exceptions
#   (log + continue), so a dead Milvus or Neo4j left `provision()` returning
#   "success" with `vectors_copied: 0` / `graph_nodes_copied: 0` — the caller
#   marked the job COMPLETED and committed a tenant with documents but zero
#   searchable vectors, with no visible error anywhere.
# - There was also no application-level ceiling on how long `provision()`
#   could hold its single Postgres transaction open, relying entirely on an
#   external `idle_in_transaction_session_timeout` that may not be configured.
#
# Both are now fixed: Milvus/Neo4j failures propagate and roll back the whole
# job exactly like a Postgres failure would (with best-effort cleanup of any
# vectors already written to the target collection in that attempt), and
# `provision()` is wrapped in an application-level `asyncio.wait_for` timeout.
# --------------------------------------------------------------------------- #


class _FakeVectorStore:
    """Minimal stand-in for the parts of VectorStorePort provisioning uses."""

    def __init__(self, records=None, fail_upsert=False, delay=0.0):
        self._records = records or []
        self._fail_upsert = fail_upsert
        self._delay = delay
        self.upserted_ids: list[str] = []
        self.deleted_ids: list[str] = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def export_vectors(self, tenant_id):
        for rec in self._records:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield rec

    async def upsert_chunks(self, chunks):
        if self._fail_upsert:
            raise RuntimeError("Milvus unreachable")
        self.upserted_ids.extend(c["chunk_id"] for c in chunks)
        return len(chunks)

    async def delete_chunks(self, chunk_ids, tenant_id):
        self.deleted_ids.extend(chunk_ids)
        return len(chunk_ids)


class _FakeNeo4jClient:
    """Minimal stand-in for the graph client methods `_copy_graph` uses."""

    def __init__(self, fail_import=False, export_delay=0.0):
        self._fail_import = fail_import
        self._export_delay = export_delay

    async def export_graph(self, tenant_id):
        if self._export_delay:
            await asyncio.sleep(self._export_delay)
        return
        yield  # pragma: no cover - makes this an async generator

    async def import_graph(self, items):
        list(items)  # drain, mirroring the real client consuming the iterator
        if self._fail_import:
            raise RuntimeError("Neo4j unreachable")
        return {"nodes_created": 0, "relationships_created": 0}


async def _seed_source_and_target(setup_session, n_docs: int = 1):
    """Seed one source tenant with `n_docs` READY docs (1 chunk each) and an
    empty target tenant + a PENDING ProvisioningJob. Returns
    (source_tenant_id, target_tenant_id, job, source_chunk_ids).
    """
    source_tenant_id = f"prov-src-{uuid.uuid4().hex[:8]}"
    target_tenant_id = f"prov-tgt-{uuid.uuid4().hex[:8]}"

    setup_session.add(Tenant(id=source_tenant_id, name="prov-source", config={}))
    setup_session.add(Tenant(id=target_tenant_id, name="prov-target", config={}))
    await setup_session.flush()

    source_chunk_ids = []
    for i in range(n_docs):
        doc = _make_source_doc(source_tenant_id, f"doc-{i}")
        setup_session.add(doc)
        chunk_id = str(uuid.uuid4())
        source_chunk_ids.append(chunk_id)
        setup_session.add(
            Chunk(
                id=chunk_id,
                tenant_id=source_tenant_id,
                document_id=doc.id,
                index=0,
                content="hello world",
                tokens=2,
                metadata_={},
            )
        )

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

    return source_tenant_id, target_tenant_id, job, source_chunk_ids


async def _assert_target_empty(session_maker, target_tenant_id: str):
    async with session_maker() as verify_session:
        await _configure(verify_session)
        docs = (
            await verify_session.execute(
                select(Document).where(Document.tenant_id == target_tenant_id)
            )
        ).scalars().all()
        assert docs == [], "Expected zero documents copied into the target tenant on failure."

        chunks = (
            await verify_session.execute(
                select(Chunk).where(Chunk.tenant_id == target_tenant_id)
            )
        ).scalars().all()
        assert chunks == [], "Expected zero chunks copied into the target tenant on failure."


async def _cleanup_tenants(session_maker, source_tenant_id, target_tenant_id, job_id):
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
            text("DELETE FROM provisioning_jobs WHERE id = :j"), {"j": job_id}
        )
        await cleanup_session.execute(
            text("DELETE FROM tenants WHERE id IN (:s, :t)"),
            {"s": source_tenant_id, "t": target_tenant_id},
        )
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_milvus_upsert_failure_fails_job_and_rolls_back_postgres(monkeypatch):
    """A Milvus write error must fail the whole job (not return `success`
    with `vectors_copied: 0`) and roll back every Postgres row this attempt
    staged, exactly like a Postgres-native failure would.
    """
    session_maker = get_session_maker()

    async with session_maker() as setup_session:
        await _configure(setup_session)
        source_tenant_id, target_tenant_id, job, source_chunk_ids = (
            await _seed_source_and_target(setup_session, n_docs=1)
        )

    from src.shared.kernel.runtime import get_settings

    monkeypatch.setattr(get_settings(), "enable_tenant_provisioning", True)

    target_collection = resolve_active_vector_collection(target_tenant_id, {})
    source_store = _FakeVectorStore(
        records=[{"chunk_id": source_chunk_ids[0], "vector": [0.1], "content": "hello world"}]
    )
    target_store = _FakeVectorStore(fail_upsert=True)

    def factory(dimensions, collection_name):
        return target_store if collection_name == target_collection else source_store

    job_session = session_maker()
    await _configure(job_session)
    service = ProvisioningService(
        session=job_session, vector_store_factory=factory, neo4j_client=_FakeNeo4jClient()
    )

    try:
        try:
            with pytest.raises(RuntimeError, match="Milvus unreachable"):
                await service.provision(job.id)
        finally:
            await job_session.close()

        await _assert_target_empty(session_maker, target_tenant_id)

        # Cleanup path attempted a best-effort delete of the (never actually
        # written) target chunk ids — harmless no-op, but proves the
        # cleanup call fired rather than being skipped.
        assert target_store.deleted_ids, "Expected cleanup to attempt deleting target vectors."
    finally:
        await _cleanup_tenants(session_maker, source_tenant_id, target_tenant_id, job.id)


@pytest.mark.asyncio
async def test_graph_copy_failure_after_vectors_succeed_cleans_up_vectors_and_rolls_back(
    monkeypatch,
):
    """Vectors copy fully succeeds, then the Neo4j graph copy fails. The
    already-written vectors reference Postgres doc/chunk ids that are about
    to be rolled back, so they must be cleaned up from the target Milvus
    collection too — not just the Postgres rows.
    """
    session_maker = get_session_maker()

    async with session_maker() as setup_session:
        await _configure(setup_session)
        source_tenant_id, target_tenant_id, job, source_chunk_ids = (
            await _seed_source_and_target(setup_session, n_docs=1)
        )
        job.include_graph = True
        await setup_session.commit()

    from src.shared.kernel.runtime import get_settings

    monkeypatch.setattr(get_settings(), "enable_tenant_provisioning", True)

    target_collection = resolve_active_vector_collection(target_tenant_id, {})
    source_store = _FakeVectorStore(
        records=[{"chunk_id": source_chunk_ids[0], "vector": [0.1], "content": "hello world"}]
    )
    target_store = _FakeVectorStore(fail_upsert=False)

    def factory(dimensions, collection_name):
        return target_store if collection_name == target_collection else source_store

    job_session = session_maker()
    await _configure(job_session)
    service = ProvisioningService(
        session=job_session,
        vector_store_factory=factory,
        neo4j_client=_FakeNeo4jClient(fail_import=True),
    )

    try:
        try:
            with pytest.raises(RuntimeError, match="Neo4j unreachable"):
                await service.provision(job.id)
        finally:
            await job_session.close()

        await _assert_target_empty(session_maker, target_tenant_id)

        # Vectors were fully upserted before the graph step failed; the
        # failure path must have deleted them from the target collection.
        assert target_store.upserted_ids, "Sanity check: vectors should have been written first."
        assert set(target_store.deleted_ids) >= set(target_store.upserted_ids), (
            "Expected the vectors written before the graph failure to be cleaned up."
        )
    finally:
        await _cleanup_tenants(session_maker, source_tenant_id, target_tenant_id, job.id)


@pytest.mark.asyncio
async def test_provision_timeout_rolls_back_postgres(monkeypatch):
    """If a step hangs past the application-level timeout, `provision()`
    must raise (not hang forever) and roll back the whole job, without
    depending on an external `idle_in_transaction_session_timeout`.
    """
    session_maker = get_session_maker()

    async with session_maker() as setup_session:
        await _configure(setup_session)
        source_tenant_id, target_tenant_id, job, source_chunk_ids = (
            await _seed_source_and_target(setup_session, n_docs=1)
        )

    from src.shared.kernel.runtime import get_settings

    monkeypatch.setattr(get_settings(), "enable_tenant_provisioning", True)
    # Shrink the timeout well below the fake store's artificial delay so the
    # test runs in a fraction of a second instead of the real 1800s ceiling.
    # 0.3s comfortably covers the real Postgres flush() for a single document
    # (steps 1-6), so the timeout reliably fires during the deliberately slow
    # Milvus read (step 7), not mid-flush — keeping the test deterministic.
    monkeypatch.setattr(provisioning_service_module, "_PROVISION_TIMEOUT_SECONDS", 0.3)

    target_collection = resolve_active_vector_collection(target_tenant_id, {})
    # `delay` makes export_vectors hang well past the shrunk timeout.
    source_store = _FakeVectorStore(
        records=[{"chunk_id": source_chunk_ids[0], "vector": [0.1], "content": "hello world"}],
        delay=2.0,
    )
    target_store = _FakeVectorStore()

    def factory(dimensions, collection_name):
        return target_store if collection_name == target_collection else source_store

    job_session = session_maker()
    await _configure(job_session)
    service = ProvisioningService(
        session=job_session, vector_store_factory=factory, neo4j_client=_FakeNeo4jClient()
    )

    try:
        try:
            with pytest.raises(TimeoutError):
                await service.provision(job.id)
        finally:
            await job_session.close()

        await _assert_target_empty(session_maker, target_tenant_id)
    finally:
        await _cleanup_tenants(session_maker, source_tenant_id, target_tenant_id, job.id)


@pytest.mark.asyncio
async def test_provision_timeout_after_vectors_written_cleans_up_vectors(monkeypatch):
    """Regression test for the cancellation edge case: `asyncio.wait_for`
    cancels the inner coroutine with `CancelledError`, a `BaseException` that
    the `except Exception` blocks around steps 7-8 do NOT catch. So a timeout
    that fires *after* vectors were already fully written to Milvus (here:
    while the Neo4j graph copy is hanging) must still clean up those vectors
    via `provision()`'s own `self._cleanup_ctx`-based handler — not rely on
    the (bypassed) inner exception handling.
    """
    session_maker = get_session_maker()

    async with session_maker() as setup_session:
        await _configure(setup_session)
        source_tenant_id, target_tenant_id, job, source_chunk_ids = (
            await _seed_source_and_target(setup_session, n_docs=1)
        )
        job.include_graph = True
        await setup_session.commit()

    from src.shared.kernel.runtime import get_settings

    monkeypatch.setattr(get_settings(), "enable_tenant_provisioning", True)
    monkeypatch.setattr(provisioning_service_module, "_PROVISION_TIMEOUT_SECONDS", 0.3)

    target_collection = resolve_active_vector_collection(target_tenant_id, {})
    source_store = _FakeVectorStore(
        records=[{"chunk_id": source_chunk_ids[0], "vector": [0.1], "content": "hello world"}]
    )
    target_store = _FakeVectorStore()

    def factory(dimensions, collection_name):
        return target_store if collection_name == target_collection else source_store

    job_session = session_maker()
    await _configure(job_session)
    service = ProvisioningService(
        session=job_session,
        vector_store_factory=factory,
        # Graph export hangs well past the shrunk timeout; vectors (step 7)
        # complete first since they have no artificial delay.
        neo4j_client=_FakeNeo4jClient(export_delay=2.0),
    )

    try:
        try:
            with pytest.raises(TimeoutError):
                await service.provision(job.id)
        finally:
            await job_session.close()

        await _assert_target_empty(session_maker, target_tenant_id)

        assert target_store.upserted_ids, "Sanity check: vectors should have been written first."
        assert set(target_store.deleted_ids) >= set(target_store.upserted_ids), (
            "Expected the vectors written before the timeout to be cleaned up, even though "
            "CancelledError bypasses the inner except-Exception cleanup path."
        )
    finally:
        await _cleanup_tenants(session_maker, source_tenant_id, target_tenant_id, job.id)


@pytest.mark.asyncio
async def test_milvus_export_shortfall_fails_job(monkeypatch):
    """`MilvusVectorStore.export_vectors` swallows its own iteration errors
    (logs a warning and stops the generator early) instead of raising, and
    its non-iterator fallback silently caps out at 16384 rows — so a Milvus
    fault during the read can surface here as a plain short result, not an
    exception. A READY source document only exists once all its chunks are
    actually embedded, so a shortfall between the chunk count and the
    exported vector count always means real vectors are missing. This must
    fail the job instead of silently copying an incomplete vector set.
    """
    session_maker = get_session_maker()

    async with session_maker() as setup_session:
        await _configure(setup_session)
        source_tenant_id, target_tenant_id, job, source_chunk_ids = (
            await _seed_source_and_target(setup_session, n_docs=2)
        )

    from src.shared.kernel.runtime import get_settings

    monkeypatch.setattr(get_settings(), "enable_tenant_provisioning", True)

    target_collection = resolve_active_vector_collection(target_tenant_id, {})
    # 2 chunks exist, but the source export only yields 1 -> shortfall.
    source_store = _FakeVectorStore(
        records=[{"chunk_id": source_chunk_ids[0], "vector": [0.1], "content": "hello world"}]
    )
    target_store = _FakeVectorStore()

    def factory(dimensions, collection_name):
        return target_store if collection_name == target_collection else source_store

    job_session = session_maker()
    await _configure(job_session)
    service = ProvisioningService(
        session=job_session, vector_store_factory=factory, neo4j_client=_FakeNeo4jClient()
    )

    try:
        try:
            with pytest.raises(RuntimeError, match="Milvus export returned 1/2 vectors"):
                await service.provision(job.id)
        finally:
            await job_session.close()

        await _assert_target_empty(session_maker, target_tenant_id)
        assert target_store.upserted_ids == [], "Nothing should have been written before the check."
    finally:
        await _cleanup_tenants(session_maker, source_tenant_id, target_tenant_id, job.id)
