"""
Provisioning Service
====================

Clones documents, chunks and vectors from a source tenant into a target
tenant without re-running the ingestion pipeline.  Called exclusively from
the ``provision_tenant`` Celery task.
"""

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

_BATCH = 50          # documents committed per transaction
_VECTOR_BATCH = 500  # Milvus chunk IDs per query


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
        """
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

        # ── 3. Stamp embedding config onto target ────────────────────── #
        await self._stamp_embedding_config(source_tenant, target_tenant)
        _progress(8)

        # ── 4. Resolve documents to copy ─────────────────────────────── #
        docs = await self._resolve_source_docs(
            source_tenant.id, job.document_ids, job.folder_ids
        )
        if not docs:
            logger.warning(f"[provision:{job_id}] No READY documents found in source — nothing to copy")
            return {"docs_copied": 0, "chunks_copied": 0, "vectors_copied": 0, "graph_nodes_copied": 0}

        _progress(10)

        # ── 5. Copy folders ───────────────────────────────────────────── #
        source_folder_ids = {d.folder_id for d in docs if d.folder_id}
        folder_id_map = await self._copy_folders(source_folder_ids, target_tenant.id)
        _progress(15)

        # ── 6. Copy documents + chunks in Postgres ────────────────────── #
        doc_id_map, chunk_id_map, old_chunk_to_old_doc = await self._copy_docs_and_chunks(
            docs, folder_id_map, target_tenant.id, _progress, start=15, end=55
        )
        _progress(55)

        # ── 7. Copy Milvus vectors ────────────────────────────────────── #
        vectors_copied = await self._copy_vectors(
            chunk_id_map, old_chunk_to_old_doc, doc_id_map,
            source_tenant, target_tenant, _progress, start=55, end=90
        )
        _progress(90)

        # ── 8. Copy Neo4j graph (optional) ────────────────────────────── #
        graph_nodes_copied = 0
        if job.include_graph:
            graph_nodes_copied = await self._copy_graph(source_tenant.id, target_tenant.id)

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
        mismatch check (EmbeddingMigrationService) passes."""
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
            await self.session.commit()
            await self.session.refresh(target)

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
        """Duplicate folders into the target tenant. Returns old_id → new_id map."""
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
            await self.session.commit()
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
        """Copy Document + Chunk rows; returns (doc_id_map, chunk_id_map, chunk→doc map)."""
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

            await self.session.commit()

            # Report sub-progress
            done = min(batch_start + _BATCH, total)
            pct = start + int((done / total) * (end - start))
            progress_fn(pct)
            logger.info(f"[provisioning] postgres {done}/{total} docs committed")

        return doc_id_map, chunk_id_map, old_chunk_to_old_doc

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
        """
        from src.core.tenants.application.active_vector_collection import (
            resolve_active_vector_collection,
        )

        src_cfg = source_tenant.config or {}
        tgt_cfg = target_tenant.config or {}

        dimensions = int(src_cfg.get("embedding_dimensions") or 1536)
        src_collection = resolve_active_vector_collection(source_tenant.id, src_cfg)
        tgt_collection = resolve_active_vector_collection(target_tenant.id, tgt_cfg)

        source_store = self.vector_store_factory(dimensions, src_collection)
        target_store = self.vector_store_factory(dimensions, tgt_collection)
        await target_store.connect()   # creates target collection if absent

        # Stream all vectors from source; filter to only the ones we're provisioning.
        # export_vectors uses output_fields=["*"] — returns ALL fields including sparse_vector.
        all_records: list[dict] = []
        async for vec in source_store.export_vectors(source_tenant.id):
            if vec.get("chunk_id") in chunk_id_map:
                all_records.append(vec)

        total = len(all_records)
        vectors_copied = 0
        errors = 0
        progress_fn(start + int(0.3 * (end - start)))   # 30% after read

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
                try:
                    n = await target_store.upsert_chunks(remapped)
                    vectors_copied += n
                except Exception as e:
                    logger.error(f"[provisioning] Milvus write error (batch {i}): {e}")
                    errors += len(remapped)

            done = min(i + _VECTOR_BATCH, total)
            pct = start + int(0.3 * (end - start)) + int((done / total) * 0.7 * (end - start))
            progress_fn(pct)
            logger.info(f"[provisioning] vectors {done}/{total} written")

        if errors:
            logger.warning(f"[provisioning] {errors} vectors failed to copy")
        return vectors_copied


    async def _copy_graph(self, source_tenant_id: str, target_tenant_id: str) -> int:
        """Copy the full Entity graph from source to target, remapping tenant_id."""
        nodes_copied = 0
        try:
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
        except Exception as e:
            logger.error(f"[provisioning] graph copy failed: {e}")
        return nodes_copied
