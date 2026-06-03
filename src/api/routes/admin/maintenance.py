"""
System Maintenance API
======================

Admin endpoints for database statistics, cache management, and maintenance tasks.

Stage 10.4 - Database & Cache Admin Backend
"""

import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_current_tenant_id, verify_super_admin

logger = logging.getLogger(__name__)

# Fix: Protect maintenance routes with admin check
router = APIRouter(
    prefix="/maintenance", tags=["admin-maintenance"], dependencies=[Depends(verify_super_admin)]
)


# =============================================================================
# Schemas
# =============================================================================


class DatabaseStats(BaseModel):
    """Database statistics."""

    documents_total: int = 0
    documents_ready: int = 0
    documents_processing: int = 0
    documents_failed: int = 0
    chunks_total: int = 0
    entities_total: int = 0
    relationships_total: int = 0
    communities_total: int = 0


class CacheStats(BaseModel):
    """Cache statistics."""

    memory_used_bytes: int = 0
    memory_max_bytes: int = 0
    memory_usage_percent: float = 0
    keys_total: int = 0
    hit_rate: float | None = None
    miss_rate: float | None = None
    evictions: int = 0


class VectorStoreStats(BaseModel):
    """Vector store statistics."""

    collections_count: int = 0
    vectors_total: int = 0
    index_size_bytes: int = 0


class SystemStats(BaseModel):
    """Combined system statistics."""

    database: DatabaseStats
    cache: CacheStats
    vector_store: VectorStoreStats
    timestamp: datetime


class StoreCounts(BaseModel):
    """Per-store document/chunk/entity counts for a single tenant."""

    tenant_id: str
    postgres_documents: int = 0
    postgres_chunks: int = 0
    neo4j_chunks: int = 0
    milvus_vectors: int = 0
    drift: bool = False


class ReconciliationStatus(BaseModel):
    """Cross-store reconciliation status (detection only, no auto-repair)."""

    sync_status: str  # "healthy" | "drift_detected" | "error"
    checked_at: datetime
    tenant_counts: list[StoreCounts] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    note: str = (
        "Detection only — reports per-tenant count mismatches between "
        "Postgres, Neo4j (:Chunk nodes), and Milvus vectors. "
        "No automatic repair is performed."
    )


class MaintenanceResult(BaseModel):
    """Result of a maintenance operation."""

    operation: str
    status: str
    message: str
    items_affected: int = 0
    duration_seconds: float = 0


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/metrics/queries", response_model=list[Any])
async def get_query_metrics(limit: int = 100, tenant_id: str | None = None):
    """
    Get recent query metrics for debugging.

    Returns detailed logs of recent queries including latency, tokens, cost, and errors.
    """
    try:
        from sqlalchemy import desc, func, select

        from src.api.config import settings
        from src.core.admin_ops.application.metrics.collector import MetricsCollector, QueryMetrics
        from src.core.admin_ops.domain.usage import UsageLog
        from src.core.database.session import async_session_maker

        # 1. Fetch real-time query metrics from Redis
        redis_metrics = []
        collector = MetricsCollector(redis_url=settings.db.redis_url)
        try:
            redis_metrics = await collector.get_recent(tenant_id=tenant_id, limit=limit)
        finally:
            await collector.close()

        # 2. Fetch aggregated ingestion logs from Postgres
        # Group by document_id (from metadata) for 'embedding' operations
        ingestion_metrics = []

        async with async_session_maker() as session:
            # We want: document_id, sum(cost), sum(total_tokens), max(created_at)
            # metadata_json->>'document_id' syntax depends on dialect, assuming Postgres

            # Using text() for JSON operator to ensure compatibility
            doc_id_expr = func.json_extract_path_text(UsageLog.metadata_json, "document_id")

            stmt = (
                select(
                    doc_id_expr.label("document_id"),
                    func.sum(UsageLog.cost).label("total_cost"),
                    func.sum(UsageLog.total_tokens).label("total_tokens"),
                    func.max(UsageLog.created_at).label("latest_at"),
                    func.max(UsageLog.model).label("model"),
                    func.max(UsageLog.provider).label("provider"),
                )
                .where(UsageLog.operation == "embedding")
                .group_by(doc_id_expr)
                .order_by(desc("latest_at"))
                .limit(limit)
            )

            if tenant_id:
                stmt = stmt.where(UsageLog.tenant_id == tenant_id)

            result = await session.execute(stmt)
            rows = result.all()

            # Resolution of Document Names
            # We fetch the filenames to show "Ingestion: filename.pdf" instead of "Ingestion: doc_123"
            from src.core.ingestion.domain.document import Document

            doc_ids = [row.document_id for row in rows if row.document_id]
            doc_map = {}

            if doc_ids:
                try:
                    stmt_docs = select(Document.id, Document.filename).where(
                        Document.id.in_(doc_ids)
                    )
                    res_docs = await session.execute(stmt_docs)
                    doc_map = {d.id: d.filename for d in res_docs.all()}
                except Exception as e:
                    logger.warning(f"Failed to resolve document names: {e}")

            for row in rows:
                if not row.document_id:
                    continue

                doc_name = doc_map.get(row.document_id, row.document_id)

                # Create a synthetic QueryMetrics object for the ingestion event
                metric = QueryMetrics(
                    query_id=f"ingest_{row.document_id}",
                    tenant_id=tenant_id
                    or "unknown",  # Row doesn't have tenant_id in group by, but we filter by it or it's mixed
                    query=f"Ingestion: {doc_name}",  # improved by frontend later
                    timestamp=row.latest_at,
                    operation="ingestion",
                    response="Document Embedding",
                    tokens_used=int(row.total_tokens or 0),
                    cost_estimate=float(row.total_cost or 0),
                    model=row.model,
                    provider=row.provider,
                    success=True,
                    # Store minimal metadata to help frontend display
                    conversation_id=doc_name,
                )
                ingestion_metrics.append(metric)

        # 3. Merge and Sort
        # Convert dataclasses to dicts if needed, or keep as objects.
        # The endpoint response_model is list[Any], so Pydantic will serialize dataclasses fine.

        all_metrics = redis_metrics + ingestion_metrics
        # Sort by timestamp descending
        # Helper to ensure timezone-aware comparison
        def _get_sort_key(m):
            ts = m.timestamp
            if ts is None:
                return datetime.min.replace(tzinfo=UTC)
            if ts.tzinfo is None:
                return ts.replace(tzinfo=UTC)
            return ts

        # Sort by timestamp descending
        all_metrics.sort(key=_get_sort_key, reverse=True)

        return all_metrics[:limit]

    except Exception as e:
        logger.error(f"Failed to get query metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/stats", response_model=SystemStats)
async def get_system_stats(
    request: Request,
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Get comprehensive system statistics.

    Returns counts and metrics from database, cache, and vector store.
    Super-admin sees cross-tenant aggregates.
    """
    try:
        is_super_admin = getattr(request.state, "is_super_admin", False)
        scope = None if is_super_admin else tenant_id
        db_stats = await _get_database_stats(scope)
        cache_stats = await _get_cache_stats(tenant_id)
        vector_stats = await _get_vector_store_stats(tenant_id)

        return SystemStats(
            database=db_stats,
            cache=cache_stats,
            vector_store=vector_stats,
            timestamp=datetime.now(UTC),
        )

    except Exception as e:
        logger.error(f"Failed to get system stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/cache/clear", response_model=MaintenanceResult)
async def clear_cache(pattern: str | None = None):
    """
    Clear Redis cache.

    - Without pattern: Clears all cache keys
    - With pattern: Clears matching keys (e.g., "query:*", "embed:*")
    """
    import time

    start = time.time()

    try:
        import redis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)

        if pattern:
            # Clear matching keys
            keys = list(r.scan_iter(match=pattern))
            if keys:
                r.delete(*keys)
            count = len(keys)
            message = f"Cleared {count} keys matching '{pattern}'"
        else:
            # Flush the database
            r.flushdb()
            count = -1  # Unknown
            message = "Flushed entire cache database"

        duration = time.time() - start
        logger.info(f"Cache cleared: {message}")

        return MaintenanceResult(
            operation="clear_cache",
            status="success",
            message=message,
            items_affected=count if count > 0 else 0,
            duration_seconds=round(duration, 3),
        )

    except ImportError as e:
        raise HTTPException(status_code=500, detail="Redis not available") from e
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/prune/orphans", response_model=MaintenanceResult)
async def prune_orphans():
    """
    Remove orphan nodes from the graph.

    Finds and removes:
    - Documents in Graph not in Postgres
    - Chunks in Graph not in Postgres
    - Entities not connected to anything
    """
    import time

    from sqlalchemy.future import select

    from src.amber_platform.composition_root import platform
    from src.core.database.session import async_session_maker
    from src.core.ingestion.domain.chunk import Chunk
    from src.core.ingestion.domain.document import Document

    start = time.time()

    try:
        # 1. Fetch valid IDs from Postgres
        async with async_session_maker() as session:
            # We fetch all IDs.
            # NOTE: Ideally this should be batched or streamed for massive datasets.
            # But for maintenance tool it's acceptable to hold ID lists in memory for now (IDs are small).
            # If > 100k docs, we should paginate.

            # Fetch valid Doc IDs
            result_docs = await session.execute(select(Document.id))
            valid_doc_ids = result_docs.scalars().all()

            # Fetch valid Chunk IDs
            result_chunks = await session.execute(select(Chunk.id))
            valid_chunk_ids = result_chunks.scalars().all()

        # 2. Call Neo4j Pruning
        # Convert UUIDs to strings just in case
        valid_doc_ids = [str(uid) for uid in valid_doc_ids]
        valid_chunk_ids = [str(uid) for uid in valid_chunk_ids]

        counts = await platform.neo4j_client.prune_orphans(valid_doc_ids, valid_chunk_ids)

        orphans_removed = sum(counts.values())
        duration = time.time() - start

        message = f"Removed orphans: {counts}"
        logger.info(f"Orphan pruning completed: {message}")

        return MaintenanceResult(
            operation="prune_orphans",
            status="success",
            message=message,
            items_affected=orphans_removed,
            duration_seconds=round(duration, 3),
        )

    except Exception as e:
        logger.error(f"Failed to prune orphans: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/prune/stale-communities", response_model=MaintenanceResult)
async def prune_stale_communities(max_age_days: int = 30):
    """
    Remove stale community summaries.

    Removes community summaries older than the specified age that haven't been refreshed.
    """
    import time

    start = time.time()

    try:
        # TODO: Implement with Neo4j
        communities_removed = 0

        duration = time.time() - start
        message = f"Removed {communities_removed} stale community summaries"

        return MaintenanceResult(
            operation="prune_stale_communities",
            status="success",
            message=message,
            items_affected=communities_removed,
            duration_seconds=round(duration, 3),
        )

    except Exception as e:
        logger.error(f"Failed to prune stale communities: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/reconciliation", response_model=ReconciliationStatus)
async def get_reconciliation_status():
    """
    Cross-store reconciliation status (detection only, no auto-repair).

    Compares per-tenant document/chunk counts from Postgres, Neo4j (:Chunk nodes),
    and Milvus vectors and reports whether the stores agree.  A mismatch means
    data is present in one store but not (yet) in another — useful to detect
    partially-failed ingestion pipelines.

    NOTE: This endpoint performs READ-only count queries and does NOT repair drift.
    """
    errors: list[str] = []
    tenant_counts: list[StoreCounts] = []

    try:
        from sqlalchemy import func
        from sqlalchemy.future import select

        from src.amber_platform.composition_root import platform
        from src.core.database.session import async_session_maker
        from src.core.ingestion.domain.chunk import Chunk
        from src.core.ingestion.domain.document import Document

        # --- 1. Postgres: documents and chunks per tenant ---
        pg_doc_counts: dict[str, int] = {}
        pg_chunk_counts: dict[str, int] = {}
        try:
            async with async_session_maker() as session:
                doc_rows = await session.execute(
                    select(Document.tenant_id, func.count(Document.id)).group_by(Document.tenant_id)
                )
                for row in doc_rows:
                    pg_doc_counts[row[0]] = row[1]

                chunk_rows = await session.execute(
                    select(Chunk.tenant_id, func.count(Chunk.id)).group_by(Chunk.tenant_id)
                )
                for row in chunk_rows:
                    pg_chunk_counts[row[0]] = row[1]
        except Exception as e:
            errors.append(f"postgres: {e}")

        # --- 2. Neo4j: :Chunk nodes per tenant ---
        neo4j_chunk_counts: dict[str, int] = {}
        try:
            cypher = """
            MATCH (c:Chunk)
            RETURN c.tenant_id AS tenant_id, count(c) AS cnt
            """
            rows = await platform.neo4j_client.execute_read(cypher, {})
            for row in rows:
                if row.get("tenant_id"):
                    neo4j_chunk_counts[row["tenant_id"]] = row["cnt"]
        except Exception as e:
            errors.append(f"neo4j: {e}")

        # --- 3. Milvus: vector count per tenant collection (amber_<tenant_id>) ---
        milvus_counts: dict[str, int] = {}
        try:
            from pymilvus import Collection, connections, utility

            milvus_host = os.getenv("MILVUS_HOST", "localhost")
            milvus_port = int(os.getenv("MILVUS_PORT", "19530"))
            try:
                connections.connect(alias="default", host=milvus_host, port=milvus_port)
            except Exception:
                pass
            for coll_name in utility.list_collections():
                if coll_name.startswith("amber_"):
                    tenant_id = coll_name[len("amber_"):]
                    try:
                        milvus_counts[tenant_id] = Collection(coll_name).num_entities
                    except Exception:
                        pass
        except ImportError:
            errors.append("milvus: pymilvus not installed")
        except Exception as e:
            errors.append(f"milvus: {e}")

        # --- 4. Build per-tenant report ---
        all_tenants = (
            set(pg_doc_counts)
            | set(pg_chunk_counts)
            | set(neo4j_chunk_counts)
            | set(milvus_counts)
        )

        drift_detected = False
        for tid in sorted(all_tenants):
            pg_docs = pg_doc_counts.get(tid, 0)
            pg_chunks = pg_chunk_counts.get(tid, 0)
            neo4j_chunks = neo4j_chunk_counts.get(tid, 0)
            milvus_vecs = milvus_counts.get(tid, 0)

            # Drift = Neo4j :Chunk count or Milvus vector count differs from Postgres chunks.
            # Milvus may have more vectors per chunk (multi-vector), so only flag strict
            # mismatches between Postgres↔Neo4j which should be 1:1 after ingestion.
            has_drift = pg_chunks != neo4j_chunks
            if has_drift:
                drift_detected = True

            tenant_counts.append(
                StoreCounts(
                    tenant_id=tid,
                    postgres_documents=pg_docs,
                    postgres_chunks=pg_chunks,
                    neo4j_chunks=neo4j_chunks,
                    milvus_vectors=milvus_vecs,
                    drift=has_drift,
                )
            )

        sync_status = "error" if errors and not tenant_counts else (
            "drift_detected" if drift_detected else "healthy"
        )

        return ReconciliationStatus(
            sync_status=sync_status,
            checked_at=datetime.now(UTC),
            tenant_counts=tenant_counts,
            errors=errors,
        )

    except Exception as e:
        logger.error(f"Failed to get reconciliation status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/reindex", response_model=MaintenanceResult)
async def trigger_reindex(collection: str | None = None):
    """
    Trigger vector index rebuild.

    - Without collection: Rebuilds all indexes
    - With collection: Rebuilds specific collection

    This is an async operation - check task status via /admin/jobs.
    """
    try:
        # Dispatch reindex task
        # TODO: Create actual reindex task in workers
        # task = celery_app.send_task("src.workers.tasks.reindex", args=[collection])

        message = f"Reindex triggered for {'all collections' if not collection else collection}"
        logger.info(message)

        return MaintenanceResult(
            operation="reindex",
            status="queued",
            message=f"{message}. Check /admin/jobs for progress.",
            items_affected=0,
            duration_seconds=0,
        )

    except Exception as e:
        logger.error(f"Failed to trigger reindex: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


class VectorCollectionInfo(BaseModel):
    """Information about a single vector collection."""

    name: str
    count: int
    dimensions: int | None = None
    index_type: str | None = None
    memory_mb: float = 0.0


class VectorCollectionsResponse(BaseModel):
    """Response with all vector collections info."""

    collections: list[VectorCollectionInfo]


@router.get("/vectors/collections", response_model=VectorCollectionsResponse)
async def get_vector_collections():
    """
    Get detailed information about all Milvus collections.

    Returns collection stats without loading collections into memory.
    Used by the Vector Store admin page.
    """
    try:
        from pymilvus import Collection, DataType, connections, utility

        # Connect to Milvus
        milvus_host = os.getenv("MILVUS_HOST", "localhost")
        milvus_port = int(os.getenv("MILVUS_PORT", "19530"))

        try:
            connections.connect(alias="default", host=milvus_host, port=milvus_port)
        except Exception:
            pass  # May already be connected

        # Get all collections
        collection_names = utility.list_collections()
        collections_info = []

        for name in collection_names:
            try:
                col = Collection(name)

                # Get vector count WITHOUT loading
                count = col.num_entities

                # Get schema to find dimensions
                dimensions = None
                for field in col.schema.fields:
                    if field.dtype == DataType.FLOAT_VECTOR:
                        dimensions = field.params.get("dim")
                        break

                # Get index type for the VECTOR field specifically
                index_type = None
                try:
                    indexes = col.indexes
                    for idx in indexes:
                        # Prefer the dense vector field index (HNSW)
                        if idx.field_name == "vector":
                            index_type = idx.params.get("index_type", "UNKNOWN")
                            break
                    # Fallback to first index if vector field not found
                    if index_type is None and indexes:
                        index_type = indexes[0].params.get("index_type", "UNKNOWN")
                except Exception:
                    pass

                # Estimate memory usage
                try:
                    stats = utility.get_collection_stats(name)
                    memory_bytes = stats.get("index_file_size", 0)
                    memory_mb = memory_bytes / (1024 * 1024) if memory_bytes else 0
                except Exception:
                    # Fallback estimation
                    if dimensions:
                        bytes_per_vector = dimensions * 4 + 100  # float32 + overhead
                        memory_mb = (count * bytes_per_vector) / (1024 * 1024)
                    else:
                        memory_mb = 0

                collections_info.append(
                    VectorCollectionInfo(
                        name=name,
                        count=count,
                        dimensions=dimensions,
                        index_type=index_type,
                        memory_mb=round(memory_mb, 2),
                    )
                )

            except Exception as e:
                logger.debug(f"Failed to get info for collection {name}: {e}")
                # Include collection with minimal info
                collections_info.append(
                    VectorCollectionInfo(
                        name=name,
                        count=0,
                    )
                )

        # Sort collections alphabetically for stable ordering
        collections_info.sort(key=lambda c: c.name)

        # Filter to only tenant-specific collections (amber_*) unless show_all requested
        collections_info = [c for c in collections_info if c.name.startswith("amber_")]

        return VectorCollectionsResponse(collections=collections_info)

    except ImportError as e:
        raise HTTPException(status_code=500, detail="Milvus client not installed") from e
    except Exception as e:
        logger.error(f"Failed to get vector collections: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.delete("/vectors/collections/{collection_name}", response_model=MaintenanceResult)
async def delete_vector_collection(collection_name: str):
    """
    Delete a Milvus vector collection.

    WARNING: This permanently deletes all vectors in the collection.
    """
    import time

    start = time.time()

    try:
        from pymilvus import Collection, connections, utility

        milvus_host = os.getenv("MILVUS_HOST", "localhost")
        milvus_port = int(os.getenv("MILVUS_PORT", "19530"))

        try:
            connections.connect(alias="default", host=milvus_host, port=milvus_port)
        except Exception:
            pass  # May already be connected

        # Check if collection exists
        if collection_name not in utility.list_collections():
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")

        # Get vector count before deletion
        col = Collection(collection_name)
        count = col.num_entities

        # Drop the collection
        utility.drop_collection(collection_name)

        duration = time.time() - start
        message = f"Deleted collection '{collection_name}' with {count} vectors"
        logger.info(message)

        return MaintenanceResult(
            operation="delete_collection",
            status="success",
            message=message,
            items_affected=count,
            duration_seconds=round(duration, 3),
        )

    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=500, detail="Milvus client not installed") from e
    except Exception as e:
        logger.error(f"Failed to delete collection: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


# =============================================================================
# Helpers
# =============================================================================


async def _get_database_stats(tenant_id: str | None) -> DatabaseStats:
    """Get PostgreSQL/Neo4j statistics with optimized queries and caching.

    ``tenant_id=None`` means aggregate across all tenants (super-admin view).
    """
    try:
        from src.core.cache.decorators import get_from_cache, set_cache

        scope_key = tenant_id or "__all__"
        cache_key = f"admin:stats:database:{scope_key}"
        cached = await get_from_cache(cache_key)
        if cached:
            return DatabaseStats(**cached)

        from sqlalchemy import case, func
        from sqlalchemy.future import select

        from src.core.database.session import async_session_maker
        from src.core.ingestion.domain.chunk import Chunk
        from src.core.ingestion.domain.document import Document
        from src.core.state.machine import DocumentStatus

        async with async_session_maker() as session:
            count_query = select(
                func.count(Document.id).label("total"),
                func.sum(case((Document.status == DocumentStatus.READY, 1), else_=0)).label(
                    "ready"
                ),
                func.sum(
                    case(
                        (
                            Document.status.in_(
                                [
                                    DocumentStatus.EXTRACTING,
                                    DocumentStatus.CLASSIFYING,
                                    DocumentStatus.CHUNKING,
                                ]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("processing"),
                func.sum(case((Document.status == DocumentStatus.FAILED, 1), else_=0)).label(
                    "failed"
                ),
            )
            if tenant_id is not None:
                count_query = count_query.where(Document.tenant_id == tenant_id)

            result = await session.execute(count_query)
            row = result.one()

            chunk_query = select(func.count(Chunk.id))
            if tenant_id is not None:
                chunk_query = chunk_query.where(Chunk.tenant_id == tenant_id)
            chunk_count = await session.scalar(chunk_query)

            # Neo4j stats: pass the same scope (None = all tenants).
            neo4j_stats = await _get_neo4j_stats_consolidated(tenant_id)

            stats = DatabaseStats(
                documents_total=row.total or 0,
                documents_ready=row.ready or 0,
                documents_processing=row.processing or 0,
                documents_failed=row.failed or 0,
                chunks_total=chunk_count or 0,
                **neo4j_stats,
            )

            # Cache for 60 seconds
            await set_cache(cache_key, stats.dict(), ttl=60)
            return stats

    except Exception as e:
        logger.warning(f"Failed to get database stats: {e}")
        return DatabaseStats()


async def _get_neo4j_stats_consolidated(tenant_id: str | None) -> dict:
    """Get all Neo4j counts in a single optimized query.

    ``tenant_id=None`` aggregates across all tenants.
    """
    try:
        from src.amber_platform.composition_root import platform

        if tenant_id is None:
            cypher = """
            MATCH (e:Entity)
            WHERE (e)<-[:MENTIONS]-()
            WITH count(e) as entity_count

            MATCH (c:Community)
            WHERE EXISTS { (:Entity)-[:BELONGS_TO|IN_COMMUNITY]->(c) }
            WITH entity_count, count(c) as community_count

            MATCH (a:Entity)-[r]->(b:Entity)
            WHERE (a)<-[:MENTIONS]-() AND (b)<-[:MENTIONS]-()
            RETURN entity_count, count(r) as rel_count, community_count
            """
            params: dict = {}
        else:
            cypher = """
            MATCH (e:Entity {tenant_id: $tenant_id})
            WHERE (e)<-[:MENTIONS]-()
            WITH count(e) as entity_count

            MATCH (c:Community {tenant_id: $tenant_id})
            WHERE EXISTS { (:Entity)-[:BELONGS_TO|IN_COMMUNITY]->(c) }
            WITH entity_count, count(c) as community_count

            MATCH (a:Entity {tenant_id: $tenant_id})-[r]->(b:Entity {tenant_id: $tenant_id})
            WHERE (a)<-[:MENTIONS]-() AND (b)<-[:MENTIONS]-()
            RETURN entity_count, count(r) as rel_count, community_count
            """
            params = {"tenant_id": tenant_id}

        result = await platform.neo4j_client.execute_read(cypher, params)
        if result and len(result) > 0:
            row = result[0]
            return {
                "entities_total": row.get("entity_count", 0),
                "relationships_total": row.get("rel_count", 0),
                "communities_total": row.get("community_count", 0),
            }
        return {"entities_total": 0, "relationships_total": 0, "communities_total": 0}

    except Exception as e:
        logger.debug(f"Failed to get Neo4j stats: {e}")
        return {"entities_total": 0, "relationships_total": 0, "communities_total": 0}


# Legacy functions kept for backwards compatibility (now call consolidated function)
async def _get_neo4j_entity_count() -> int:
    """Get entity count from Neo4j. (Deprecated - use _get_neo4j_stats_consolidated)"""
    stats = await _get_neo4j_stats_consolidated(None)
    return stats.get("entities_total", 0)


async def _get_neo4j_relationship_count() -> int:
    """Get relationship count from Neo4j. (Deprecated - use _get_neo4j_stats_consolidated)"""
    stats = await _get_neo4j_stats_consolidated(None)
    return stats.get("relationships_total", 0)


async def _get_neo4j_community_count() -> int:
    """Get community count from Neo4j. (Deprecated - use _get_neo4j_stats_consolidated)"""
    stats = await _get_neo4j_stats_consolidated(None)
    return stats.get("communities_total", 0)


async def _get_cache_stats(tenant_id: str) -> CacheStats:
    """Get Redis cache statistics."""
    try:
        import redis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)

        info = r.info("memory")
        stats = r.info("stats")

        used = info.get("used_memory", 0)
        max_mem = info.get("maxmemory", 0) or used * 2  # Estimate if not set

        hits = stats.get("keyspace_hits", 0)
        misses = stats.get("keyspace_misses", 0)
        total = hits + misses

        return CacheStats(
            memory_used_bytes=used,
            memory_max_bytes=max_mem,
            memory_usage_percent=round((used / max_mem) * 100, 2) if max_mem > 0 else 0,
            keys_total=r.dbsize(),
            hit_rate=round((hits / total) * 100, 2) if total > 0 else None,
            miss_rate=round((misses / total) * 100, 2) if total > 0 else None,
            evictions=stats.get("evicted_keys", 0),
        )
    except Exception as e:
        logger.warning(f"Failed to get cache stats: {e}")
        return CacheStats()


async def _get_vector_store_stats(tenant_id: str) -> VectorStoreStats:
    """Get Milvus vector store statistics with caching (optimized - no col.load())."""
    try:
        from src.core.cache.decorators import get_from_cache, set_cache

        # Check cache first
        cache_key = f"admin:stats:vectors:{tenant_id}"
        cached = await get_from_cache(cache_key)
        if cached:
            return VectorStoreStats(**cached)

        import os

        from pymilvus import Collection, connections, utility

        # Connect to Milvus
        milvus_host = os.getenv("MILVUS_HOST", "localhost")
        milvus_port = int(os.getenv("MILVUS_PORT", "19530"))

        # Check if already connected, if not connect
        try:
            connections.connect(alias="default", host=milvus_host, port=milvus_port)
        except Exception:
            pass  # May already be connected

        # Get all collections
        collections = utility.list_collections()
        collections_count = len(collections)

        # Count total vectors across all collections
        vectors_total = 0
        index_size_bytes = 0

        for coll_name in collections:
            try:
                col = Collection(coll_name)
                # CRITICAL FIX: Use num_entities WITHOUT loading collection into memory
                # col.num_entities queries metadata only, doesn't load vectors
                vectors_total += col.num_entities

                # Get collection stats (lightweight operation)
                try:
                    stats = utility.get_collection_stats(coll_name)
                    # Try to get actual index size if available
                    index_size_bytes += stats.get("index_file_size", 0)
                except Exception:
                    pass  # Stats not available, will use estimation below

            except Exception as e:
                logger.debug(f"Failed to get stats for collection {coll_name}: {e}")

        # If we couldn't get actual index size, estimate it
        if index_size_bytes == 0 and vectors_total > 0:
            # Rough estimate (each vector ~1536 dims * 4 bytes + overhead)
            estimated_bytes_per_vector = 1536 * 4 + 100  # 6244 bytes approx
            index_size_bytes = vectors_total * estimated_bytes_per_vector

        stats = VectorStoreStats(
            collections_count=collections_count,
            vectors_total=vectors_total,
            index_size_bytes=index_size_bytes,
        )

        # Cache for 60 seconds
        await set_cache(cache_key, stats.dict(), ttl=60)
        return stats

    except ImportError:
        logger.debug("pymilvus not installed, skipping vector store stats")
        return VectorStoreStats()
    except Exception as e:
        logger.warning(f"Failed to get vector store stats: {e}")
        return VectorStoreStats()
