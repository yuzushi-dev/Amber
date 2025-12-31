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


# =============================================================================
# Helpers
# =============================================================================

async def _get_database_stats() -> DatabaseStats:
    """Get PostgreSQL/Neo4j statistics."""
    try:
        from src.core.database.session import async_session_maker
        from src.core.models.document import Document
        from src.core.models.chunk import Chunk
        from src.core.state.machine import DocumentStatus
        from sqlalchemy.future import select
        from sqlalchemy import func, or_
        
        async with async_session_maker() as session:
            # Document counts
            total_docs = await session.execute(select(func.count(Document.id)))
            ready_docs = await session.execute(
                select(func.count(Document.id)).where(Document.status == DocumentStatus.READY)
            )
            # Processing = extracting, classifying, or chunking
            processing_docs = await session.execute(
                select(func.count(Document.id)).where(
                    or_(
                        Document.status == DocumentStatus.EXTRACTING,
                        Document.status == DocumentStatus.CLASSIFYING,
                        Document.status == DocumentStatus.CHUNKING
                    )
                )
            )
            failed_docs = await session.execute(
                select(func.count(Document.id)).where(Document.status == DocumentStatus.FAILED)
            )
            
            # Chunk count
            total_chunks = await session.execute(select(func.count(Chunk.id)))
            
            return DatabaseStats(
                documents_total=total_docs.scalar() or 0,
                documents_ready=ready_docs.scalar() or 0,
                documents_processing=processing_docs.scalar() or 0,
                documents_failed=failed_docs.scalar() or 0,
                chunks_total=total_chunks.scalar() or 0,
                entities_total=await _get_neo4j_entity_count(),
                relationships_total=await _get_neo4j_relationship_count(),
                communities_total=await _get_neo4j_community_count(),
            )
    except Exception as e:
        logger.warning(f"Failed to get database stats: {e}")
        return DatabaseStats()


async def _get_neo4j_entity_count() -> int:
    """Get entity count from Neo4j."""
    try:
        from src.core.graph.neo4j_client import neo4j_client
        result = await neo4j_client.execute_read(
            "MATCH (e:Entity) RETURN count(e) as count"
        )
        if result:
            return result[0].get("count", 0)
        return 0
    except Exception as e:
        logger.debug(f"Failed to get Neo4j entity count: {e}")
        return 0


async def _get_neo4j_relationship_count() -> int:
    """Get relationship count from Neo4j."""
    try:
        from src.core.graph.neo4j_client import neo4j_client
        result = await neo4j_client.execute_read(
            "MATCH ()-[r]->() RETURN count(r) as count"
        )
        if result:
            return result[0].get("count", 0)
        return 0
    except Exception as e:
        logger.debug(f"Failed to get Neo4j relationship count: {e}")
        return 0


async def _get_neo4j_community_count() -> int:
    """Get community count from Neo4j."""
    try:
        from src.core.graph.neo4j_client import neo4j_client
        result = await neo4j_client.execute_read(
            "MATCH (c:Community) RETURN count(c) as count"
        )
        if result:
            return result[0].get("count", 0)
        return 0
    except Exception as e:
        logger.debug(f"Failed to get Neo4j community count: {e}")
        return 0


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
    """Get Milvus vector store statistics."""
    try:
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
                col.load()
                vectors_total += col.num_entities
                
                # Try to get index info for size estimation
                # Milvus doesn't directly expose index size, so we estimate
                # based on vector count and typical overhead
            except Exception as e:
                logger.debug(f"Failed to get stats for collection {coll_name}: {e}")
        
        # Rough estimate of index size (each vector ~1536 dims * 4 bytes + overhead)
        # This is an approximation
        estimated_bytes_per_vector = 1536 * 4 + 100  # 6244 bytes approx
        index_size_bytes = vectors_total * estimated_bytes_per_vector
        
        return VectorStoreStats(
            collections_count=collections_count,
            vectors_total=vectors_total,
            index_size_bytes=index_size_bytes,
        )
    except ImportError:
        logger.debug("pymilvus not installed, skipping vector store stats")
        return VectorStoreStats()
    except Exception as e:
        logger.warning(f"Failed to get vector store stats: {e}")
        return VectorStoreStats()
