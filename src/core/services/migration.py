"""
Embedding Migration Service
===========================

Handles the detection of embedding model mismatches and orchestrates the migration process.
"""

import logging
from typing import List, Dict, Any, Optional

from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import settings
from src.core.models.tenant import Tenant
from src.core.models.document import Document
from src.core.models.chunk import Chunk
from src.core.state.machine import DocumentStatus
from src.core.vector_store.milvus import MilvusVectorStore, MilvusConfig
from src.core.events.dispatcher import EventDispatcher, StateChangeEvent

logger = logging.getLogger(__name__)


class EmbeddingMigrationService:
    """
    Manages embedding model compatibility and migration.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_compatibility_status(self) -> List[Dict[str, Any]]:
        """
        Check all tenants for embedding model compatibility using Tenant.config.
        
        Returns:
            List of status dicts per tenant.
        """
        query = select(Tenant).where(Tenant.is_active == True)
        result = await self.session.execute(query)
        tenants = result.scalars().all()

        statuses = []
        for tenant in tenants:
            # Get stored config or default to empty
            tenant_config = tenant.config or {}
            
            # Extract stored model info
            stored_provider = tenant_config.get("embedding_provider")
            stored_model = tenant_config.get("embedding_model")
            stored_dims = tenant_config.get("embedding_dimensions")
            
            # Current system config
            current_provider = settings.default_embedding_provider
            current_model = settings.default_embedding_model
            current_dims = settings.embedding_dimensions
            
            # If no stored config, it might be a legacy tenant or fresh install.
            # We assume legacy tenants match the OLD default (e.g. text-embedding-3-small) 
            # OR we count it as "UNKNOWN" requiring manual check.
            # For robustness:
            # - If tenant has NO documents/chunks, it's compatible (auto-update).
            # - If tenant has vectors, we might be risking mismatch.
            
            is_compatible = True
            details = "Compatible"
            
            # Initialize chunk_count default
            chunk_count = 0 
           
            if not stored_model:
                # No record. Check if they have data.
                # If they have no chunks, we can just stamp it now.
                chunk_count = await self._get_chunk_count(tenant.id)
                if chunk_count > 0:
                    # They have data but no config. This is risky.
                    # We flag it as 'LEGACY' - might match or not.
                    is_compatible = False # Force explicit confirmation
                    details = "Legacy Data (No Model Metadata)"
                else:
                    # Empty tenant, compatible
                    details = "Empty (Auto-Stamp Candidate)"
            
            else:
                # Compare - BUT relax the check against system config.
                # If stored config exists, we treat it as the source of truth for INTENT.
                # Compatibility is now defined as: Does Stored Config match Actual Data?
                
                # If stored_model is different from current_model, it's a "Custom Configuration".
                # We only flag INCOMPATIBLE if the stored config implies we shouldn't be able to run?
                # Actually, migration is needed if:
                # 1. Stored Config != Actual Milvus Data (Critical)
                # 2. Stored Model is deprecated/invalid (Hard to check without list)
                
                # For now, we assume if they have a config, they want that config.
                if (stored_provider != current_provider or 
                    stored_model != current_model or 
                    stored_dims != current_dims):
                    # It's a custom config. 
                    is_compatible = True # It IS compatible with itself.
                    details = f"Custom: Using {stored_model} ({stored_dims}d) (System default: {current_model})"
                else:
                    details = "Compatible (Matches System Default)"

            # ALSO check actual Milvus dimensions - the vectors in storage may not match config
            milvus_dims = await self._get_milvus_dimensions(tenant.id)
            if milvus_dims:
                # If we have vectors, they MUST match the stored config dimensions
                if milvus_dims != stored_dims:
                    is_compatible = False
                    details = f"Milvus Mismatch: Stored vectors are {milvus_dims}d but config expects {stored_dims}d"
            elif chunk_count > 0:
                 # Chunks but no collection? Mismatch.
                 # Or maybe collection exists but empty?
                 pass

            statuses.append({
                "tenant_id": tenant.id,
                "tenant_name": tenant.name,
                "is_compatible": is_compatible,
                "stored_config": {
                    "provider": stored_provider,
                    "model": stored_model,
                    "dimensions": stored_dims
                },
                "system_config": {
                    "provider": current_provider,
                    "model": current_model,
                    "dimensions": current_dims
                },
                "milvus_dimensions": milvus_dims,
                "details": details
            })


        return statuses

    async def _get_chunk_count(self, tenant_id: str) -> int:
        from sqlalchemy import func
        query = select(func.count(Chunk.id)).where(Chunk.tenant_id == tenant_id)
        return (await self.session.execute(query)).scalar() or 0

    async def _get_milvus_dimensions(self, tenant_id: str) -> Optional[int]:
        """Get actual vector dimensions from Milvus collection for this tenant."""
        try:
            from pymilvus import Collection, DataType, connections, utility
            import os
            
            milvus_host = os.getenv("MILVUS_HOST", "localhost")
            milvus_port = int(os.getenv("MILVUS_PORT", "19530"))
            
            try:
                connections.connect(alias="default", host=milvus_host, port=milvus_port)
            except Exception:
                pass  # May already be connected
            
            collection_name = f"amber_{tenant_id}"
            if collection_name not in utility.list_collections():
                return None  # No collection yet
            
            col = Collection(collection_name)
            for field in col.schema.fields:
                if field.dtype == DataType.FLOAT_VECTOR:
                    return field.params.get("dim")
            return None
        except Exception as e:
            logger.debug(f"Failed to get Milvus dimensions for {tenant_id}: {e}")
            return None

    async def migrate_tenant(self, tenant_id: str) -> Dict[str, Any]:
        """
        Perform destructive migration for a tenant.
        
        1. Drop Vector Collection
        2. Delete Chunk records
        3. Reset Document Config/Status
        4. Update Tenant Config (if needed)
        """
        logger.warning(f"Starting destructive embedding migration for tenant {tenant_id}")
        
        # 1. Update Tenant Config First (Locking in the new model)
        query = select(Tenant).where(Tenant.id == tenant_id)
        tenant = (await self.session.execute(query)).scalars().first()
        if not tenant:
            raise ValueError("Tenant not found")
            
        new_config = tenant.config.copy() if tenant.config else {}
        
        # KEY CHANGE: Do NOT blindly overwrite with system settings.
        # Ensure we have all necessary fields. Use existing config if present.
        
        if "embedding_provider" not in new_config:
            new_config["embedding_provider"] = settings.default_embedding_provider
        if "embedding_model" not in new_config:
            new_config["embedding_model"] = settings.default_embedding_model

        # Define model-to-provider mapping
        MODEL_PROVIDERS = {
            "text-embedding-3-small": "openai",
            "text-embedding-3-large": "openai",
            "text-embedding-ada-002": "openai",
            "voyage-3.5-lite": "voyage",
            "bge-m3": "local",
            "nomic-embed-text": "ollama",
            "mxbai-embed-large": "ollama",
            "all-minilm": "ollama"
        }
            
        # RESOLVE DIMENSIONS based on model if possible
        # This ensures that if we switch model, we switch dimensions too.
        # The frontend doesn't usually send dimensions, just the model.
        MODEL_DIMENSIONS = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
            "voyage-3.5-lite": 1536,
            "bge-m3": 1024,
            "nomic-embed-text": 768,
            "mxbai-embed-large": 1024,
            "all-minilm": 384
        }
        
        model = new_config.get("embedding_model")
        current_provider = new_config.get("embedding_provider")
        
        # 1. Infer provider only if missing (Legacy support)
        if not current_provider and model in MODEL_PROVIDERS:
            new_config["embedding_provider"] = MODEL_PROVIDERS[model]
        
        # 2. Force update dimensions if model is known
        if model in MODEL_DIMENSIONS:
            new_config["embedding_dimensions"] = MODEL_DIMENSIONS[model]
        elif "embedding_dimensions" not in new_config:
            new_config["embedding_dimensions"] = settings.embedding_dimensions or 1536

        # Always update migration timestamp
        new_config["migrated_at"] = str(import_datetime().isoformat())

        tenant.config = new_config
        self.session.add(tenant)
        
        # 2. Drop Milvus Collection
        # Note: In single-collection architecture (document_chunks), this drops ALL data.
        # This is expected for a global model migration.
        config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name=f"amber_{tenant_id}", 
            dimensions=new_config["embedding_dimensions"]
        )
        store = MilvusVectorStore(config)
        dropped = await store.drop_collection()
        
        # FIX: Pre-create the collection to avoid race condition
        # Workers will now find an existing collection instead of racing to create it
        await store.connect()
        logger.info(f"Pre-created collection amber_{tenant_id} with {new_config['embedding_dimensions']} dimensions")
        
        # Also drop the legacy/global one just in case
        legacy_config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name="document_chunks", 
        )
        legacy_store = MilvusVectorStore(legacy_config)
        await legacy_store.drop_collection()
        
        # 3. Clear Neo4j Graph
        # We must clear the graph as it depends on chunks/embeddings we are about to delete.
        from src.core.graph.neo4j_client import neo4j_client
        deleted_nodes = await neo4j_client.delete_tenant_data(tenant_id)
        logger.info(f"Deleted {deleted_nodes} nodes from Neo4j for tenant {tenant_id}")

        # 4. Delete Chunks from DB
        # This cascades to embeddings usually, but we manage Milvus separately
        del_query = delete(Chunk).where(Chunk.tenant_id == tenant_id)
        result = await self.session.execute(del_query)
        chunks_deleted = result.rowcount
        
        # 4. Reset Documents to INGESTED (so they get picked up by ingestion loop)
        # Note: We reset from READY/failed back to INGESTED. 
        # We assume file storage is intact.
        
        # First, search all the documents for this tenant
        doc_ids_query = select(Document.id).where(Document.tenant_id == tenant_id)
        doc_ids_result = await self.session.execute(doc_ids_query)
        doc_ids = doc_ids_result.scalars().all()
        
        doc_query = update(Document).where(
            Document.tenant_id == tenant_id
        ).values(
            status=DocumentStatus.INGESTED,
            # We assume we want to re-extract too to be safe/clean? 
            # Or straight to CHUNKING?
            # Creating new chunks implies cleaning extraction cache? 
            # Safest is INGESTED -> re-run full pipeline.
            error_message=None
        )
        result = await self.session.execute(doc_query)
        docs_reset = result.rowcount
        
        await self.session.commit()
        
        # 5. Kick off re-ingestion (Optional: automated or rely on poller)
        # If we have a poller, it will pick up INGESTED docs.
        # If not, we might need to trigger explicit tasks.
        # For now, let's rely on the natural status transition.
        from src.workers.tasks import process_document
        task_ids = []
        for doc_id in doc_ids:
            res = process_document.delay(doc_id, tenant_id)
            task_ids.append(res.id)
        
        logger.info(f"Migration complete for {tenant_id}: {chunks_deleted} chunks deleted, {docs_reset} docs reset. {len(task_ids)} tasks queued.")
        
        return {
            "status": "success",
            "chunks_deleted": chunks_deleted,
            "docs_queued": docs_reset,
            "task_ids": task_ids,
            "new_model": new_config["embedding_model"]
        }

    async def cancel_tenant_migration(self, task_ids: List[str]):
        """
        Revoke all pending/active tasks for a migration.
        """
        if not task_ids:
            return
            
        from src.workers.celery_app import celery_app
        logger.warning(f"Revoking {len(task_ids)} tasks for cancelled migration")
        
        for task_id in task_ids:
            # terminate=True sends SIGTERM to the worker process running the task
            celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')

def import_datetime():
    from datetime import datetime
    return datetime.now()
