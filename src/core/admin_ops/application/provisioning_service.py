"""
Provisioning Service
====================

Clones documents, chunks and vectors from a source tenant into a target
tenant without re-running the ingestion pipeline.  Called exclusively from
the ``provision_tenant`` Celery task.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.admin_ops.application.provisioning_policy import ensure_tenant_provisioning_enabled
from src.core.admin_ops.domain.provisioning_job import ProvisioningJob
from src.core.ingestion.domain.chunk import Chunk, EmbeddingStatus
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant

logger = logging.getLogger(__name__)

_BATCH = 50          # documents flushed (not committed) per round-trip; the whole
                     # job is a single Postgres transaction, committed once by the
                     # caller after `provision()` returns successfully.
_VECTOR_BATCH = 500  # Milvus chunk IDs per query

# Application-level ceiling on the whole `provision()` run (job lookup through
# the final Milvus/Neo4j copy). Provisioning holds a single open Postgres
# transaction for its entire duration (see the module docstring / provision()
# below), so a hang here — e.g. Milvus or Neo4j wedged mid-copy — would
# otherwise keep that transaction (and any locks/replication slots it holds)
# open indefinitely, and correctness must not depend on an external
# `idle_in_transaction_session_timeout` being configured on the Postgres
# server. 30 minutes is comfortably under the Celery `task_soft_time_limit`
# of 3600s (see src/workers/celery_app.py) so this timeout fires and rolls
# back cleanly well before Celery would SIGTERM/SIGKILL the worker process,
# while still being generous enough for the largest realistic provisioning
# job (a handful of thousand documents).
_PROVISION_TIMEOUT_SECONDS = 1800


class ProvisioningService:
    """Copies tenant data (postgres rows + Milvus vectors + optionally Neo4j graph)
    from a source tenant to an already-created target tenant."""

    def __init__(
        self,
        session: AsyncSession,
        vector_store_factory: Callable,
        neo4j_client: Any,
    ):
        self.session = session
        self.vector_store_factory = vector_store_factory
        self.neo4j_client = neo4j_client
        # Set by `_provision_inner` once Postgres staging (step 6) finishes;
        # read by `provision()`'s timeout handler. See the NOTE in
        # `provision()`'s docstring for why this can't just be a local var.
        self._cleanup_ctx: tuple[dict[str, str], Tenant, Tenant] | None = None

    # ------------------------------------------------------------------ #
    # Public entry point                                                   #
    # ------------------------------------------------------------------ #

    async def provision(
        self,
        job_id: str,
        progress_callback: Callable[[int], None] | None = None,
    ) -> dict:
        """Execute the provisioning job identified by *job_id*.

        Returns a dict with result counters on success.
        Raises on unrecoverable errors (caller marks the job FAILED).

        Wrapped in an application-level timeout (`_PROVISION_TIMEOUT_SECONDS`)
        so a wedged Milvus/Neo4j call (or an unexpectedly huge document set)
        cannot hold the underlying Postgres transaction open forever — see
        the constant's docstring for why this must not rely on an external
        `idle_in_transaction_session_timeout`.

        NOTE on cancellation: `asyncio.wait_for` cancels the inner coroutine
        by raising `CancelledError` inside it. `CancelledError` is a
        `BaseException`, not an `Exception`, so it is NOT caught by the
        `except Exception` blocks inside `_provision_inner` (steps 3-6 and
        7-8) — it unwinds straight past them to here. That's why the Milvus
        vector cleanup on a timeout is done here, from `self._cleanup_ctx`
        (populated by `_provision_inner` once step 6 finishes), rather than
        relying on the inner try/except blocks to have run.
        """
        self._cleanup_ctx = None  # reset in case this instance is reused across calls
        try:
            return await asyncio.wait_for(
                self._provision_inner(job_id, progress_callback),
                timeout=_PROVISION_TIMEOUT_SECONDS,
            )
        except TimeoutError as original:
            logger.error(
                f"[provision:{job_id}] Provisioning exceeded the "
                f"{_PROVISION_TIMEOUT_SECONDS}s application-level timeout — rolling back "
                "and failing the job rather than leaving the transaction open indefinitely."
            )
            if self._cleanup_ctx is not None:
                chunk_id_map, source_tenant, target_tenant = self._cleanup_ctx
                await self._cleanup_target_vectors(
                    job_id, chunk_id_map, source_tenant, target_tenant
                )
            try:
                await self.session.rollback()
            except Exception:
                logger.exception(
                    f"[provision:{job_id}] Rollback after timeout also failed — the "
                    "connection may already be unusable; it will be discarded by the pool."
                )
            raise TimeoutError(
                f"Provisioning job {job_id} exceeded the {_PROVISION_TIMEOUT_SECONDS}s "
                "application-level timeout"
            ) from original

    async def _provision_inner(
        self,
        job_id: str,
        progress_callback: Callable[[int], None] | None,
    ) -> dict:
        def _progress(pct: int):
            if progress_callback:
                progress_callback(pct)

        # ── 1. Load job ──────────────────────────────────────────────── #
        job = await self._load_job(job_id)

        ensure_tenant_provisioning_enabled()
        logger.warning(
            "[provision:%s] Legacy tenant provisioning explicitly enabled; this path duplicates tenant data.",
            job_id,
        )

        # ── 2. Load tenants ──────────────────────────────────────────── #
        source_tenant = await self._get_tenant(job.source_tenant_id)
        target_tenant = await self._get_tenant(job.target_tenant_id)
        if not source_tenant:
            raise ValueError(f"Source tenant '{job.source_tenant_id}' not found")
        if not target_tenant:
            raise ValueError(f"Target tenant '{job.target_tenant_id}' not found")

        _progress(5)

        # ── 3-8. Copy postgres rows, then vectors/graph ──────────────── #
        #
        # Everything that writes to Postgres (embedding-config stamp, folders,
        # documents, chunks) happens on the SAME session/transaction and is
        # only ever flushed, never committed, until this method returns
        # successfully. The caller (provision_tenant / _provision_async)
        # issues the single commit once the job is marked COMPLETED, so a
        # job that dies partway through — e.g. a retry that re-copies a
        # document whose content_hash already exists in the target tenant
        # and trips `uq_documents_tenant_content_hash` — leaves ZERO rows
        # behind: the exception propagates, we roll back everything this
        # job has staged, and re-raise so the caller marks the job FAILED.
        # This also makes retries idempotent: a failed run never leaves a
        # partial target state that a subsequent run has to reconcile with.
        try:
            # ── 3. Stamp embedding config onto target ────────────────── #
            await self._stamp_embedding_config(source_tenant, target_tenant)
            _progress(8)

            # ── 4. Resolve documents to copy ─────────────────────────── #
            docs = await self._resolve_source_docs(
                source_tenant.id, job.document_ids, job.folder_ids
            )
            if not docs:
                logger.warning(
                    f"[provision:{job_id}] No READY documents found in source — nothing to copy"
                )
                return {
                    "docs_copied": 0,
                    "chunks_copied": 0,
                    "vectors_copied": 0,
                    "graph_nodes_copied": 0,
                }

            _progress(10)

            # ── 5. Copy folders ───────────────────────────────────────── #
            source_folder_ids = {d.folder_id for d in docs if d.folder_id}
            folder_id_map = await self._copy_folders(source_folder_ids, target_tenant.id)
            _progress(15)

            # ── 6. Copy documents + chunks in Postgres ────────────────── #
            doc_id_map, chunk_id_map, old_chunk_to_old_doc = await self._copy_docs_and_chunks(
                docs, folder_id_map, target_tenant.id, _progress, start=15, end=55
            )
            _progress(55)
        except Exception:
            logger.exception(
                f"[provision:{job_id}] Postgres copy failed — rolling back the entire job "
                "(no partial documents/chunks/folders left behind)."
            )
            await self.session.rollback()
            raise

        # Make (chunk_id_map, source_tenant, target_tenant) reachable from
        # `provision()`'s timeout handler: `CancelledError` (raised by
        # `asyncio.wait_for` on timeout) is a BaseException and skips the
        # `except Exception` blocks below, so that handler can't rely on a
        # local variable here — it reads this instance attribute instead.
        # See the NOTE in `provision()`'s docstring.
        self._cleanup_ctx = (chunk_id_map, source_tenant, target_tenant)

        # ── 7-8. Copy Milvus vectors, then the Neo4j graph ────────────── #
        #
        # Same rollback contract as steps 3-6: this is still inside the
        # job-wide transaction (nothing from step 6 has been committed yet),
        # so any failure here must roll back the Postgres side exactly like
        # a Postgres-native failure would — a target tenant with documents
        # but zero searchable vectors is not a valid "completed" outcome.
        # Both `_copy_vectors` and `_copy_graph` raise (rather than
        # swallowing) on any error. On the way out we also best-effort clean
        # up any vectors this attempt may have already written to the target
        # Milvus collection — this covers BOTH a partial `_copy_vectors`
        # failure AND a `_copy_graph` failure that happens *after*
        # `_copy_vectors` fully succeeded (in which case fully-written
        # vectors would otherwise reference Postgres doc/chunk ids that are
        # about to be rolled back and never committed). This job's Postgres
        # doc/chunk ids are freshly generated per attempt (see
        # `_copy_docs_and_chunks`), so a retry never reuses this attempt's
        # ids — anything left behind here would be a permanent orphan that
        # no later retry ever cleans up. `_copy_graph` needs no equivalent
        # cleanup of its own: Neo4j import is MERGE-based on a stable
        # (name, tenant_id) key, so a retry safely reconciles with whatever
        # a previous partial attempt already wrote (see its docstring).
        try:
            vectors_copied = await self._copy_vectors(
                chunk_id_map, old_chunk_to_old_doc, doc_id_map,
                source_tenant, target_tenant, _progress, start=55, end=90
            )
            _progress(90)

            graph_nodes_copied = 0
            if job.include_graph:
                graph_nodes_copied = await self._copy_graph(source_tenant.id, target_tenant.id)
        except Exception:
            logger.exception(
                f"[provision:{job_id}] Vector/graph copy failed — rolling back the entire job "
                "(no partial documents/chunks/folders left behind)."
            )
            await self._cleanup_target_vectors(job_id, chunk_id_map, source_tenant, target_tenant)
            await self.session.rollback()
            raise

        _progress(100)

        return {
            "docs_copied": len(doc_id_map),
            "chunks_copied": len(chunk_id_map),
            "vectors_copied": vectors_copied,
            "graph_nodes_copied": graph_nodes_copied,
        }

    # ------------------------------------------------------------------ #
    # Step helpers                                                         #
    # ------------------------------------------------------------------ #

    async def _load_job(self, job_id: str) -> ProvisioningJob:
        result = await self.session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError(f"ProvisioningJob '{job_id}' not found")
        return job

    async def _get_tenant(self, tenant_id: str) -> Tenant | None:
        result = await self.session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def _stamp_embedding_config(self, source: Tenant, target: Tenant) -> None:
        """Copy embedding model config from source to target so the startup
        mismatch check (EmbeddingMigrationService) passes.

        Flushes (does not commit) so this stays inside the single job-wide
        transaction — see the try/except around steps 3-6 in `provision()`.
        """
        src_cfg = source.config or {}
        tgt_cfg = dict(target.config or {})
        keys = ("embedding_provider", "embedding_model", "embedding_dimensions")
        changed = False
        for k in keys:
            if k in src_cfg and k not in tgt_cfg:
                tgt_cfg[k] = src_cfg[k]
                changed = True
        if changed:
            target.config = tgt_cfg
            await self.session.flush()

    async def _resolve_source_docs(
        self,
        source_tenant_id: str,
        document_ids: list[str] | None,
        folder_ids: list[str] | None,
    ) -> list[Document]:
        """Return the Documents to be provisioned, with their chunks pre-loaded."""
        q = (
            select(Document)
            .where(Document.tenant_id == source_tenant_id)
            .where(Document.status == DocumentStatus.READY)
            .options(selectinload(Document.chunks))
        )
        if document_ids:
            q = q.where(Document.id.in_(document_ids))
        elif folder_ids:
            q = q.where(Document.folder_id.in_(folder_ids))

        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def _copy_folders(
        self, source_folder_ids: set[str], target_tenant_id: str
    ) -> dict[str, str]:
        """Duplicate folders into the target tenant. Returns old_id → new_id map.

        Flushes (does not commit) — stays inside the job-wide transaction.
        """
        if not source_folder_ids:
            return {}
        result = await self.session.execute(
            select(Folder).where(Folder.id.in_(source_folder_ids))
        )
        folder_id_map: dict[str, str] = {}
        for src_folder in result.scalars().all():
            new_id = str(uuid4())
            new_folder = Folder(id=new_id, tenant_id=target_tenant_id, name=src_folder.name)
            self.session.add(new_folder)
            folder_id_map[src_folder.id] = new_id
        if folder_id_map:
            await self.session.flush()
        return folder_id_map

    async def _copy_docs_and_chunks(
        self,
        docs: list[Document],
        folder_id_map: dict[str, str],
        target_tenant_id: str,
        progress_fn: Callable[[int], None],
        start: int,
        end: int,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        """Copy Document + Chunk rows; returns (doc_id_map, chunk_id_map, chunk→doc map).

        Flushes per batch of `_BATCH` documents (to bound memory / surface
        constraint violations early via round-trips to the DB) but never
        commits — the whole job commits atomically once, in the caller,
        after `provision()` returns successfully. See the try/except around
        steps 3-6 in `provision()` for the rollback-on-failure path.
        """
        doc_id_map: dict[str, str] = {}           # old_doc_id  → new_doc_id
        chunk_id_map: dict[str, str] = {}          # old_chunk_id → new_chunk_id
        old_chunk_to_old_doc: dict[str, str] = {}  # old_chunk_id → old_doc_id

        total = len(docs)
        for batch_start in range(0, total, _BATCH):
            batch = docs[batch_start: batch_start + _BATCH]
            for doc in batch:
                new_doc_id = str(uuid4())
                doc_id_map[doc.id] = new_doc_id

                new_doc = Document(
                    id=new_doc_id,
                    tenant_id=target_tenant_id,
                    filename=doc.filename,
                    content_hash=doc.content_hash,
                    storage_path=doc.storage_path,   # shared reference, no S3 copy
                    status=DocumentStatus.READY,
                    domain=doc.domain,
                    source_type=doc.source_type,
                    source_url=doc.source_url,
                    metadata_=dict(doc.metadata_) if doc.metadata_ else {},
                    summary=doc.summary,
                    document_type=doc.document_type,
                    keywords=list(doc.keywords) if doc.keywords else [],
                    hashtags=list(doc.hashtags) if doc.hashtags else [],
                    folder_id=folder_id_map.get(doc.folder_id) if doc.folder_id else None,
                )
                self.session.add(new_doc)

                for chunk in doc.chunks:
                    new_chunk_id = str(uuid4())
                    chunk_id_map[chunk.id] = new_chunk_id
                    old_chunk_to_old_doc[chunk.id] = doc.id

                    new_chunk = Chunk(
                        id=new_chunk_id,
                        tenant_id=target_tenant_id,
                        document_id=new_doc_id,
                        index=chunk.index,
                        content=chunk.content,
                        tokens=chunk.tokens,
                        metadata_=dict(chunk.metadata_) if chunk.metadata_ else {},
                        embedding_status=EmbeddingStatus.COMPLETED,
                    )
                    self.session.add(new_chunk)

            await self.session.flush()

            # Report sub-progress
            done = min(batch_start + _BATCH, total)
            pct = start + int((done / total) * (end - start))
            progress_fn(pct)
            logger.info(f"[provisioning] postgres {done}/{total} docs staged (flushed, not yet committed)")

        return doc_id_map, chunk_id_map, old_chunk_to_old_doc

    def _resolve_vector_store(self, tenant: Tenant, dimensions: int):
        """Build the vector store handle for *tenant*'s active collection.

        Factored out so the failure-path cleanup in `provision()` can reach
        the same target collection `_copy_vectors` writes to, without
        duplicating the dimension/collection-name resolution logic.
        """
        from src.core.tenants.application.active_vector_collection import (
            resolve_active_vector_collection,
        )

        cfg = tenant.config or {}
        collection = resolve_active_vector_collection(tenant.id, cfg)
        return self.vector_store_factory(dimensions, collection)

    async def _cleanup_target_vectors(
        self,
        job_id: str,
        chunk_id_map: dict[str, str],
        source_tenant: Tenant,
        target_tenant: Tenant,
    ) -> None:
        """Best-effort delete of any vectors this attempt may have written.

        Called from `provision()`'s failure path for steps 7-8. Covers both
        a partial `_copy_vectors` failure and a `_copy_graph` failure that
        happens *after* `_copy_vectors` fully succeeded — in both cases,
        whatever vectors already landed in the target collection reference
        Postgres doc/chunk ids that are about to be rolled back and will
        never be committed, so leaving them in Milvus would be a permanent,
        silent orphan (this job's ids are freshly generated per attempt, so
        no future retry will ever reference — or clean up — these ids).
        Deleting ids that were never actually written is a harmless no-op.

        NOTE on `connect()` below: it creates the target Milvus collection if
        absent. In every failure path that reaches here through an exception
        raised inside `_copy_vectors` (the shortfall check, or any upsert
        error), `_copy_vectors` itself already called `target_store.connect()`
        unconditionally before either of those raise points, so this is a
        harmless re-connect to a collection that already exists -- it does
        not create anything new. The only path where this call could be the
        one actually creating the collection is a timeout that lands mid
        cancellation during `_copy_vectors`'s own `connect()` call, before it
        completes; in that narrow race this may leave an empty target
        collection behind despite the job having been rolled back. Accepted
        as a low-severity residual: it holds zero vectors, gets reused
        harmlessly if the tenant is provisioned again, and is dropped by the
        tenant-deletion path (`cleanup_tenant_vectors`) if the tenant never is.
        """
        if not chunk_id_map:
            return
        try:
            src_cfg = source_tenant.config or {}
            dimensions = int(src_cfg.get("embedding_dimensions") or 1536)
            target_store = self._resolve_vector_store(target_tenant, dimensions)
            await target_store.connect()
            await target_store.delete_chunks(list(chunk_id_map.values()), target_tenant.id)
            logger.info(
                f"[provision:{job_id}] cleaned up up to {len(chunk_id_map)} target vectors "
                "after a step 7/8 failure."
            )
        except Exception:
            logger.exception(
                f"[provision:{job_id}] failed to clean up target vectors after a step 7/8 "
                f"failure — manual cleanup of tenant {target_tenant.id}'s vector collection "
                "may be required."
            )

    async def _copy_vectors(
        self,
        chunk_id_map: dict[str, str],
        old_chunk_to_old_doc: dict[str, str],
        doc_id_map: dict[str, str],
        source_tenant: Tenant,
        target_tenant: Tenant,
        progress_fn: Callable[[int], None],
        start: int,
        end: int,
    ) -> int:
        """Read vectors from source Milvus collection (all fields), remap IDs, write to target.

        Uses export_vectors with output_fields='*' so that dynamic fields like
        sparse_vector are included — avoids the 'missing field' error on upsert.

        Fails fast on BOTH ends of the copy:

        - On read: if the source export returns fewer records than there are
          chunks to copy, that's treated as a hard failure, not a legitimate
          zero — see the shortfall check below for why.
        - On write: ANY batch write error aborts the whole copy (raises)
          instead of logging and continuing.

        Provisioning is a rare, admin-triggered operation over a bounded,
        known document set — not a hot path where a fuzzy error-rate
        tolerance would pay for its own complexity. Silently returning
        `vectors_copied` under the expected count used to leave a tenant
        "provisioned" with documents but no searchable vectors and no
        visible error; failing fast is simpler and strictly safer, and the
        caller can just retry once Milvus is healthy. Cleanup of whatever
        this attempt already wrote to the target collection happens in the
        caller (`provision()`), via `_cleanup_target_vectors` — see that
        method's docstring.
        """
        src_cfg = source_tenant.config or {}

        dimensions = int(src_cfg.get("embedding_dimensions") or 1536)
        source_store = self._resolve_vector_store(source_tenant, dimensions)
        target_store = self._resolve_vector_store(target_tenant, dimensions)
        await target_store.connect()   # creates target collection if absent

        # Stream all vectors from source; filter to only the ones we're provisioning.
        # export_vectors uses output_fields=["*"] — returns ALL fields including sparse_vector.
        all_records: list[dict] = []
        async for vec in source_store.export_vectors(source_tenant.id):
            if vec.get("chunk_id") in chunk_id_map:
                all_records.append(vec)

        total = len(all_records)
        expected = len(chunk_id_map)
        if total < expected:
            # `export_vectors` (MilvusVectorStore) swallows its own iteration
            # errors: it logs a warning and stops the generator early instead
            # of raising, and its non-iterator fallback silently caps out at
            # 16384 rows. Either way that reads here as a plain (short)
            # result, not an exception — so we can't rely on the try/except
            # below to catch a truncated read. Every chunk we're about to
            # copy already carries `embedding_status=COMPLETED` (see
            # `_copy_docs_and_chunks`) because a READY source document is
            # only reachable once all its chunks are actually embedded (see
            # ingestion_service's embedding step), so a shortfall here always
            # means real vectors are missing from the source export — never
            # "not embedded yet" — and copying it forward would silently
            # promise the target chunks are searchable when they are not.
            raise RuntimeError(
                f"Milvus export returned {total}/{expected} vectors for source tenant "
                f"{source_tenant.id} — aborting provisioning rather than copying an "
                "incomplete (possibly truncated) vector set."
            )
        vectors_copied = 0
        progress_fn(start + int(0.3 * (end - start)))   # 30% after read

        try:
            for i in range(0, total, _VECTOR_BATCH):
                batch = all_records[i: i + _VECTOR_BATCH]
                remapped = []
                for rec in batch:
                    old_cid = rec.get("chunk_id")
                    old_did = old_chunk_to_old_doc.get(old_cid, "")
                    row = {
                        "chunk_id": chunk_id_map[old_cid],
                        "document_id": doc_id_map.get(old_did, old_did),
                        "tenant_id": target_tenant.id,
                        "content": rec.get("content", ""),
                        "embedding": rec.get("vector"),      # upsert_chunks expects 'embedding'
                    }
                    # Pass sparse_vector through if present (required by Milvus schema)
                    sparse = rec.get("sparse_vector")
                    if sparse is not None:
                        row["sparse_vector"] = sparse
                    remapped.append(row)

                if remapped:
                    n = await target_store.upsert_chunks(remapped)
                    vectors_copied += n

                done = min(i + _VECTOR_BATCH, total)
                pct = start + int(0.3 * (end - start)) + int((done / total) * 0.7 * (end - start))
                progress_fn(pct)
                logger.info(f"[provisioning] vectors {done}/{total} written")
        except Exception:
            logger.exception(
                f"[provisioning] Milvus write error after {vectors_copied}/{total} vectors "
                "written — aborting the provisioning job (fail-fast: any write error fails "
                "the job rather than risking a silently under-vectorized tenant). Cleanup of "
                "any already-written vectors happens in provision()'s failure path."
            )
            raise

        return vectors_copied

    async def _copy_graph(self, source_tenant_id: str, target_tenant_id: str) -> int:
        """Copy the full Entity graph from source to target, remapping tenant_id.

        Does NOT swallow errors: any failure propagates so `provision()` rolls
        back the whole job, consistent with `_copy_vectors`. Unlike vectors,
        no explicit cleanup is needed on failure/retry: `import_graph` MERGEs
        nodes on `(name, tenant_id)` and relationships via
        `apoc.merge.relationship` (see Neo4jClient._import_nodes_batch /
        _import_rels_batch) — both stable keys independent of this job's
        per-attempt Postgres ids — so re-running this after a partial failure
        reconciles safely instead of creating duplicates or orphans.
        """
        items: list[dict] = []
        async for item in self.neo4j_client.export_graph(source_tenant_id):
            if item.get("type") == "node":
                props = dict(item.get("properties", {}))
                props["tenant_id"] = target_tenant_id
                item = dict(item)
                item["properties"] = props
            elif item.get("type") == "relationship":
                item = dict(item)
                item["tenant_id"] = target_tenant_id
            items.append(item)

        stats = await self.neo4j_client.import_graph(iter(items))
        nodes_copied = stats.get("nodes_created", 0)
        logger.info(f"[provisioning] graph copy done: {stats}")
        return nodes_copied
