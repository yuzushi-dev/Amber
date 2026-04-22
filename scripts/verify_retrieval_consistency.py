import asyncio
import logging
import os
import sys
from typing import Any

# Adjust path to include project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.api.config import settings
from src.api.schemas.query import QueryOptions, QueryRequest
from src.core.database.session import configure_database
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.retrieval.application.use_cases_query import QueryUseCase
from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
TENANT_ID = "default"
USER_ID = "verification_script"
QUERY_TEXT = "What are the main themes regarding the protagonist's journey?"
SEED = 42
Iterations = 3

async def main():
    logger.info("Starting Retrieval Consistency Verification...")

    # Configure DB (Host: 5433 as per docker-compose)
    db_url = settings.db.database_url.replace(":5432", ":5433")
    configure_database(db_url)

    # Force Localhost for Ollama (Direct settings patch)
    settings.ollama_base_url = "http://localhost:11434/v1"

    # Configure Provider Factory
    from src.core.generation.domain.ports.provider_factory import set_provider_factory_builder
    from src.core.generation.infrastructure.providers.factory import ProviderFactory
    set_provider_factory_builder(ProviderFactory)
    from src.core.generation.domain.ports.provider_factory import set_provider_factory_builder
    from src.core.generation.infrastructure.providers.factory import ProviderFactory
    set_provider_factory_builder(ProviderFactory)

    # 1. Initialize Components directly (skipping full DI container for simplicity if possible, or mocking)
    # Actually, we need real DB access.

    from src.api.deps import _get_async_session_maker
    session_maker = _get_async_session_maker()

    async with session_maker() as session:
        # Repositories
        doc_repo = PostgresDocumentRepository(session)
        tenant_repo = PostgresTenantRepository(session)

        # We need to ensure tenant config has seed=42
        tenant = await tenant_repo.get(TENANT_ID)
        if not tenant:
            logger.error(f"Tenant {TENANT_ID} not found.")
            return

        # Update tenant config to enforce seed/temp
        from sqlalchemy.orm.attributes import flag_modified

        if not tenant.config:
            tenant.config = {}

        tenant.config["seed"] = SEED
        tenant.config["temperature"] = 0.0

        # Flag as modified to ensure SQLAlchemy detects JSON mutation
        flag_modified(tenant, "config")

        # await tenant_repo.update(TENANT_ID, {"config": tenant.config})
        await session.commit()
        logger.info(f"Enforced tenant config: Seed={SEED}, Temp=0.0")

        # Services
        # Retrieval Service depends on Vector Store
        # We might need to instantiate Milvus client directly if not using DI
        # Let's try to use the composition root helpers if importable
        try:
            from src.amber_platform.composition_root import (
                build_generation_service,
                build_metrics_collector,
                build_retrieval_service,
            )

            retrieval_service = build_retrieval_service(session)
            generation_service = build_generation_service(session)
            metrics_collector = build_metrics_collector()

            use_case = QueryUseCase(
                retrieval_service=retrieval_service,
                generation_service=generation_service,
                metrics_collector=metrics_collector
            )

            request = QueryRequest(
                query=QUERY_TEXT,
                options=QueryOptions(
                    agent_mode=False,
                    max_chunks=5
                )
            )

            results: list[dict[str, Any]] = []

            for i in range(Iterations):
                logger.info(f"\n--- Run {i+1}/{Iterations} ---")

                response = await use_case.execute(
                    request=request,
                    tenant_id=TENANT_ID,
                    http_request_state=None, # Might fail if state is accessed directly without checks
                    user_id=USER_ID
                )

                # Extract key metrics
                # 1. Retrieved Chunk IDs
                sources = response.sources
                chunk_ids = sorted([s.chunk_id for s in sources])

                # 2. Answer Hash/Token Count
                answer = response.answer

                results.append({
                    "run": i + 1,
                    "chunk_ids": chunk_ids,
                    "answer_len": len(answer),
                    "answer_preview": answer[:50],
                    "sources_count": len(sources)
                })

                logger.info(f"Retrieved {len(sources)} chunks: {chunk_ids[:3]}...")
                logger.info(f"Answer: {answer[:50]}...")

            # Analysis
            logger.info("\n--- Verification Report ---")

            # Check Retrieval Stability
            base_chunks = results[0]["chunk_ids"]
            retrieval_match = all(r["chunk_ids"] == base_chunks for r in results)

            if retrieval_match:
                logger.info("✅ Retrieval Consistency: PASS (Identical chunks retrieved)")
            else:
                logger.error("❌ Retrieval Consistency: FAIL (Chunks vary across runs)")
                for r in results:
                    logger.info(f"Run {r['run']}: {r['chunk_ids']}")

            # Check Generation Stability (Exact Match unlikely even with seed, but length should be close)
            # Actually with temp=0 and seed=42, it SHOULD be exact match for modern models usually
            base_answer = results[0]["answer_preview"]
            answer_match = all(r["answer_preview"] == base_answer for r in results)

            if answer_match:
                logger.info("✅ Generation Consistency: PASS (Identical start)")
            else:
                logger.warning("⚠️ Generation Consistency: VARIANCE DETECTED")
                for r in results:
                    logger.info(f"Run {r['run']}: {r['answer_preview']}")

        except Exception as e:
            logger.exception(f"Verification failed: {e}")

        finally:
            # Restore config (optional, maybe good to leave it set for user to see)
            # tenant.config = original_config
            # await tenant_repo.update(TENANT_ID, {"config": tenant.config})
            # await session.commit()
            pass

if __name__ == "__main__":
    asyncio.run(main())
