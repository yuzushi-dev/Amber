"""
Embedding Migration Service
===========================

Handles the detection of embedding model mismatches and orchestrates the migration process.
"""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.graph.domain.ports.graph_client import GraphClientPort
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.ports.dispatcher import TaskDispatcher
from src.core.retrieval.domain.ports.vector_store_admin_port import VectorStoreAdminPort
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant
from src.shared.model_registry import (
    EMBEDDING_MODELS,
    LEGACY_EMBEDDING_DIMENSIONS,
    LEGACY_EMBEDDING_PROVIDERS,
)

logger = logging.getLogger(__name__)


class EmbeddingMigrationService:
    """
    Manages embedding model compatibility and migration.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Any,  # Typed as Any or Protocol
        task_dispatcher: TaskDispatcher,
        graph_client: GraphClientPort,
        vector_store_factory: Callable[[int, str | None], VectorStoreAdminPort],
    ):
        self.session = session
        self.settings = settings
        self.task_dispatcher = task_dispatcher
        self.graph_client = graph_client
        self.vector_store_factory = vector_store_factory

    async def get_compatibility_status(self) -> list[dict[str, Any]]:
        """
        Check all tenants for embedding model compatibility using Tenant.config.

        Returns:
            List of status dicts per tenant.
        """
        query = select(Tenant).where(Tenant.is_active)
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
            current_provider = self.settings.default_embedding_provider
            current_model = self.settings.default_embedding_model
            current_dims = self.settings.embedding_dimensions

            # If no stored config, it might be a legacy tenant or fresh install.
            # We assume legacy tenants match the previous default embedding model
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
                    is_compatible = False  # Force explicit confirmation
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
                if (
                    stored_provider != current_provider
                    or stored_model != current_model
                    or stored_dims != current_dims
                ):
                    # It's a custom config.
                    is_compatible = True  # It IS compatible with itself.
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

            statuses.append(
                {
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "is_compatible": is_compatible,
                    "stored_config": {
                        "provider": stored_provider,
                        "model": stored_model,
                        "dimensions": stored_dims,
                    },
                    "system_config": {
                        "provider": current_provider,
                        "model": current_model,
                        "dimensions": current_dims,
                    },
                    "milvus_dimensions": milvus_dims,
                    "details": details,
                }
            )

        return statuses

    async def _get_chunk_count(self, tenant_id: str) -> int:
        from sqlalchemy import func

        query = select(func.count(Chunk.id)).where(Chunk.tenant_id == tenant_id)
        return (await self.session.execute(query)).scalar() or 0

    async def _get_milvus_dimensions(self, tenant_id: str) -> int | None:
        """Get actual vector dimensions from Milvus collection for this tenant."""
        try:
            dimensions = self.settings.embedding_dimensions or 1536
            store = self.vector_store_factory(dimensions, collection_name=f"amber_{tenant_id}")
            return await store.get_collection_dimensions()
        except Exception as e:
            logger.debug(f"Failed to get vector dimensions for {tenant_id}: {e}")
            return None

    async def migrate_tenant(self, tenant_id: str) -> dict[str, Any]:
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
            new_config["embedding_provider"] = self.settings.default_embedding_provider
        if "embedding_model" not in new_config:
            new_config["embedding_model"] = self.settings.default_embedding_model

        # Define model-to-provider mapping
        MODEL_PROVIDERS = {
            model: provider
            for provider, models in EMBEDDING_MODELS.items()
            for model in models.keys()
        }
        MODEL_PROVIDERS.update(LEGACY_EMBEDDING_PROVIDERS)

        # RESOLVE DIMENSIONS based on model if possible
        # This ensures that if we switch model, we switch dimensions too.
        # The frontend doesn't usually send dimensions, just the model.
        MODEL_DIMENSIONS = {
            model: info["dimensions"]
            for provider, models in EMBEDDING_MODELS.items()
            for model, info in models.items()
            if "dimensions" in info
        }
        MODEL_DIMENSIONS.update(LEGACY_EMBEDDING_DIMENSIONS)

        model = new_config.get("embedding_model")
        current_provider = new_config.get("embedding_provider")

        # 1. Infer provider only if missing (Legacy support)
        if not current_provider and model in MODEL_PROVIDERS:
            new_config["embedding_provider"] = MODEL_PROVIDERS[model]

        # 2. Force update dimensions if model is known
        new_config["embedding_dimensions"] = await self._resolve_dimensions(
            new_config.get("embedding_provider", "openai"), model
        )

        # Always update migration timestamp
        new_config["migrated_at"] = str(import_datetime().isoformat())

        tenant.config = new_config
        self.session.add(tenant)

        # 2. Drop Milvus Collection
        # Note: In single-collection architecture (document_chunks), this drops ALL data.
        # This is expected for a global model migration.
        store = self.vector_store_factory(
            new_config["embedding_dimensions"],
            collection_name=f"amber_{tenant_id}",
        )
        await store.drop_collection()

        # FIX: Pre-create the collection to avoid race condition
        # Workers will now find an existing collection instead of racing to create it
        await store.connect()
        logger.info(
            f"Pre-created collection amber_{tenant_id} with {new_config['embedding_dimensions']} dimensions"
        )

        # Also drop the legacy/global one just in case
        legacy_store = self.vector_store_factory(
            new_config["embedding_dimensions"],
            collection_name="document_chunks",
        )
        await legacy_store.drop_collection()

        # 3. Clear Neo4j Graph
        # We must clear the graph as it depends on chunks/embeddings we are about to delete.
        # Use Python-side batching to avoid Neo4j MemoryPoolOutOfMemoryError
        total_deleted = 0
        while True:
            delete_query = """
            MATCH (n {tenant_id: $tenant_id})
            WITH n LIMIT 1000
            DETACH DELETE n
            RETURN count(n) as count
            """
            result = await self.graph_client.execute_write(delete_query, {"tenant_id": tenant_id})
            count = result[0]["count"] if result else 0
            total_deleted += count
            logger.debug(f"Deleted batch of {count} nodes...")

            if count == 0:
                break

        deleted_nodes = total_deleted
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

        doc_query = (
            update(Document)
            .where(Document.tenant_id == tenant_id)
            .values(
                status=DocumentStatus.INGESTED,
                # We assume we want to re-extract too to be safe/clean?
                # Or straight to CHUNKING?
                # Creating new chunks implies cleaning extraction cache?
                # Safest is INGESTED -> re-run full pipeline.
                error_message=None,
            )
        )
        result = await self.session.execute(doc_query)
        docs_reset = result.rowcount

        await self.session.commit()

        # 5. Kick off re-ingestion (Optional: automated or rely on poller)
        # If we have a poller, it will pick up INGESTED docs.
        # If not, we might need to trigger explicit tasks.
        # For now, let's rely on the natural status transition.
        task_ids = []
        for doc_id in doc_ids:
            task_id = await self.task_dispatcher.dispatch(
                "src.workers.tasks.process_document", args=[doc_id, tenant_id]
            )
            task_ids.append(task_id)

        logger.info(
            f"Migration complete for {tenant_id}: {chunks_deleted} chunks deleted, {docs_reset} docs reset. {len(task_ids)} tasks queued."
        )

        return {
            "status": "success",
            "chunks_deleted": chunks_deleted,
            "docs_queued": docs_reset,
            "task_ids": task_ids,
            "new_model": new_config["embedding_model"],
        }

    async def _resolve_dimensions(self, provider: str, model: str) -> int:
        """
        Determine embedding dimensions for a given model.

        1. Checks hardcoded list (MODEL_DIMENSIONS)
        2. Tries to match by stripping ':<tag>'
        3. Falls back to dynamic generation check
        """
        # Hardcoded defaults
        MODEL_DIMENSIONS = {
            model: info["dimensions"]
            for provider_name, models in EMBEDDING_MODELS.items()
            for model, info in models.items()
            if "dimensions" in info
        }
        MODEL_DIMENSIONS.update(LEGACY_EMBEDDING_DIMENSIONS)

        # 1. Exact match
        if model in MODEL_DIMENSIONS:
            return MODEL_DIMENSIONS[model]

        # 2. Base match (strip :tag)
        base_model = model.split(":")[0]
        if base_model in MODEL_DIMENSIONS:
            return MODEL_DIMENSIONS[base_model]

        # 3. Dynamic Resolution
        try:
            logger.info(f"Resolving dimensions dynamically for {model}...")

            from src.core.generation.domain.ports.provider_factory import (
                build_provider_factory,
                get_provider_factory,
            )
            from src.core.retrieval.application.embeddings_service import EmbeddingService

            # We instantiate a temporary service just for this check
            try:
                factory = build_provider_factory(
                    openai_api_key=self.settings.openai_api_key,
                    ollama_base_url=self.settings.ollama_base_url,
                    default_embedding_provider=provider,
                    default_embedding_model=model,
                )
            except RuntimeError:
                factory = get_provider_factory()

            temp_service = EmbeddingService(
                provider=factory.get_embedding_provider(
                    provider_name=provider,
                    model=model,
                ),
                model=model,
                # Start with default, but we care about output
                dimensions=1536,
            )

            # Generate one dummy embedding
            embeddings, _ = await temp_service.embed_texts(["dimension_check"])

            if embeddings and len(embeddings) > 0:
                actual_dim = len(embeddings[0])
                logger.info(f"Dynamically resolved {model} dimensions to {actual_dim}")
                return actual_dim

        except Exception as e:
            logger.warning(
                f"Failed to dynamically resolve dimensions for {model}: {e}. Defaulting to 1536."
            )

        # Fallback
        return 1536

    async def cancel_tenant_migration(self, task_ids: list[str]):
        """
        Revoke all pending/active tasks for a migration.
        """
        if not task_ids:
            return

        logger.warning(f"Revoking {len(task_ids)} tasks for cancelled migration")

        for task_id in task_ids:
            # terminate=True sends SIGTERM to the worker process running the task
            await self.task_dispatcher.cancel_task(task_id, terminate=True)


def import_datetime():
    from datetime import datetime

    return datetime.now()
