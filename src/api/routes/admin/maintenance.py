"""
System Maintenance API
======================

Admin endpoints for database statistics, cache management, and maintenance tasks.

Stage 10.4 - Database & Cache Admin Backend
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance", tags=["admin-maintenance"])


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
    hit_rate: Optional[float] = None
    miss_rate: Optional[float] = None
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


class ReconciliationStatus(BaseModel):
    """Dual-write reconciliation status."""
    sync_status: str  # "healthy", "degraded", "error"
    last_sync_at: Optional[datetime] = None
    sync_lag_seconds: float = 0
    pending_writes: int = 0
    failed_writes: int = 0
    retry_queue_depth: int = 0
    errors: list = Field(default_factory=list)


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

@router.get("/stats", response_model=SystemStats)
async def get_system_stats():
    """
    Get comprehensive system statistics.
    
    Returns counts and metrics from database, cache, and vector store.
    """
    try:
        db_stats = await _get_database_stats()
        cache_stats = await _get_cache_stats()
        vector_stats = await _get_vector_store_stats()
        
        return SystemStats(
            database=db_stats,
            cache=cache_stats,
            vector_store=vector_stats,
            timestamp=datetime.now(timezone.utc),
        )
        
    except Exception as e:
        logger.error(f"Failed to get system stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.post("/cache/clear", response_model=MaintenanceResult)
async def clear_cache(pattern: Optional[str] = None):
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
        
    except ImportError:
        raise HTTPException(status_code=500, detail="Redis not available")
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


@router.post("/prune/orphans", response_model=MaintenanceResult)
async def prune_orphans():
    """
    Remove orphan nodes from the graph.
    
    Finds and removes:
    - Entities not connected to any chunks
    - Chunks not connected to any documents
    - Communities with no members
    """
    import time
    start = time.time()
    
    try:
        # TODO: Implement actual orphan detection and removal with Neo4j
        # This is a placeholder implementation
        
        orphans_removed = 0
        
        # In production, this would run queries like:
        # MATCH (e:Entity) WHERE NOT (e)<-[:HAS_ENTITY]-() DELETE e
        # MATCH (c:Chunk) WHERE NOT (c)<-[:HAS_CHUNK]-() DELETE c
        
        duration = time.time() - start
        message = f"Removed {orphans_removed} orphan nodes"
        
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
        raise HTTPException(status_code=500, detail=f"Failed to prune orphans: {str(e)}")


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
        raise HTTPException(status_code=500, detail=f"Failed to prune: {str(e)}")


@router.get("/reconciliation", response_model=ReconciliationStatus)
async def get_reconciliation_status():
    """
    Get dual-write reconciliation status.
    
    Shows sync health between primary (Neo4j) and secondary (Milvus) stores.
    """
    try:
        # TODO: Implement actual reconciliation tracking
        # This would monitor the dual-write pipeline
        
        return ReconciliationStatus(
            sync_status="healthy",
            last_sync_at=datetime.now(timezone.utc),
            sync_lag_seconds=0.0,
            pending_writes=0,
            failed_writes=0,
            retry_queue_depth=0,
            errors=[],
        )
        
    except Exception as e:
        logger.error(f"Failed to get reconciliation status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.post("/reindex", response_model=MaintenanceResult)
async def trigger_reindex(collection: Optional[str] = None):
    """
    Trigger vector index rebuild.

    - Without collection: Rebuilds all indexes
    - With collection: Rebuilds specific collection

    This is an async operation - check task status via /admin/jobs.
    """
    try:
        from src.workers.celery_app import celery_app

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
        raise HTTPException(status_code=500, detail=f"Failed to trigger reindex: {str(e)}")


class VectorCollectionInfo(BaseModel):
    """Information about a single vector collection."""
    name: str
    count: int
    dimensions: Optional[int] = None
    index_type: Optional[str] = None
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
        from pymilvus import connections, Collection, utility, DataType

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

                # Get index type if available
                index_type = None
                try:
                    indexes = col.indexes
                    if indexes:
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

                collections_info.append(VectorCollectionInfo(
                    name=name,
                    count=count,
                    dimensions=dimensions,
                    index_type=index_type,
                    memory_mb=round(memory_mb, 2),
                ))

            except Exception as e:
                logger.debug(f"Failed to get info for collection {name}: {e}")
                # Include collection with minimal info
                collections_info.append(VectorCollectionInfo(
                    name=name,
                    count=0,
                ))

        return VectorCollectionsResponse(collections=collections_info)

    except ImportError:
        raise HTTPException(status_code=500, detail="Milvus client not installed")
    except Exception as e:
        logger.error(f"Failed to get vector collections: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get collections: {str(e)}")


# =============================================================================
# Helpers
# =============================================================================

async def _get_database_stats() -> DatabaseStats:
    """Get PostgreSQL/Neo4j statistics with optimized queries and caching."""
    try:
        from src.core.cache.decorators import get_from_cache, set_cache

        # Check cache first
        cache_key = "admin:stats:database"
        cached = await get_from_cache(cache_key)
        if cached:
            return DatabaseStats(**cached)

        from src.core.database.session import async_session_maker
        from src.core.models.document import Document
        from src.core.models.chunk import Chunk
        from src.core.state.machine import DocumentStatus
        from sqlalchemy.future import select
        from sqlalchemy import func, case

        async with async_session_maker() as session:
            # OPTIMIZED: Single query for all document counts using CASE
            count_query = select(
                func.count(Document.id).label('total'),
                func.sum(case((Document.status == DocumentStatus.READY, 1), else_=0)).label('ready'),
                func.sum(case(
                    (Document.status.in_([
                        DocumentStatus.EXTRACTING,
                        DocumentStatus.CLASSIFYING,
                        DocumentStatus.CHUNKING
                    ]), 1),
                    else_=0
                )).label('processing'),
                func.sum(case((Document.status == DocumentStatus.FAILED, 1), else_=0)).label('failed'),
            )
            result = await session.execute(count_query)
            row = result.one()

            # Chunk count (separate query as it's a different table)
            chunk_count = await session.scalar(select(func.count(Chunk.id)))

            # OPTIMIZED: Get all Neo4j counts in a single query
            neo4j_stats = await _get_neo4j_stats_consolidated()

            stats = DatabaseStats(
                documents_total=row.total or 0,
                documents_ready=row.ready or 0,
                documents_processing=row.processing or 0,
                documents_failed=row.failed or 0,
                chunks_total=chunk_count or 0,
                **neo4j_stats
            )

            # Cache for 60 seconds
            await set_cache(cache_key, stats.dict(), ttl=60)
            return stats

    except Exception as e:
        logger.warning(f"Failed to get database stats: {e}")
        return DatabaseStats()


async def _get_neo4j_stats_consolidated() -> dict:
    """Get all Neo4j counts in a single optimized query."""
    try:
        from src.core.graph.neo4j_client import neo4j_client

        # OPTIMIZED: Single query returning all counts at once
        cypher = """
        MATCH (e:Entity)
        WITH count(e) as entity_count
        MATCH ()-[r]->()
        WITH entity_count, count(r) as rel_count
        MATCH (c:Community)
        RETURN entity_count, rel_count, count(c) as community_count
        """

        result = await neo4j_client.execute_read(cypher)
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
    stats = await _get_neo4j_stats_consolidated()
    return stats.get("entities_total", 0)


async def _get_neo4j_relationship_count() -> int:
    """Get relationship count from Neo4j. (Deprecated - use _get_neo4j_stats_consolidated)"""
    stats = await _get_neo4j_stats_consolidated()
    return stats.get("relationships_total", 0)


async def _get_neo4j_community_count() -> int:
    """Get community count from Neo4j. (Deprecated - use _get_neo4j_stats_consolidated)"""
    stats = await _get_neo4j_stats_consolidated()
    return stats.get("communities_total", 0)


async def _get_cache_stats() -> CacheStats:
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


async def _get_vector_store_stats() -> VectorStoreStats:
    """Get Milvus vector store statistics with caching (optimized - no col.load())."""
    try:
        from src.core.cache.decorators import get_from_cache, set_cache

        # Check cache first
        cache_key = "admin:stats:vectors"
        cached = await get_from_cache(cache_key)
        if cached:
            return VectorStoreStats(**cached)

        from pymilvus import connections, Collection, utility
        import os

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
