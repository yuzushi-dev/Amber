# ruff: noqa: E402

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database.session import configure_database

# 1. Define Test Tenant Constant
TEST_TENANT_ID = "integration_test_tenant"

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://graphrag:graphrag@localhost:5433/graphrag",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("MILVUS_HOST", "localhost")
os.environ.setdefault("MILVUS_PORT", "19530")
os.environ.setdefault("MINIO_HOST", "localhost")
os.environ.setdefault("MINIO_PORT", "9000")

# Configure Database
configure_database(os.environ["DATABASE_URL"])

from src.api.main import app
from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant
from src.shared.security import generate_api_key, hash_api_key


@pytest.fixture(scope="function", autouse=True)
def initialize_application():
    """Initialize the application state (providers, settings) for every test."""
    # Configure Settings
    from src.amber_platform.composition_root import configure_settings
    from src.api.config import settings

    configure_settings(settings)

    # Configure Graph Client
    from src.amber_platform.composition_root import platform
    from src.core.graph.domain.ports.graph_client import set_graph_client

    set_graph_client(platform.neo4j_client)

    # Configure Content Extractor
    from src.core.ingestion.domain.ports.content_extractor import set_content_extractor
    from src.core.ingestion.infrastructure.extraction.fallback_extractor import (
        FallbackContentExtractor,
    )

    set_content_extractor(FallbackContentExtractor())

    # Configure Provider Factory
    from src.core.generation.domain.ports.provider_factory import set_provider_factory_builder
    from src.core.generation.infrastructure.providers.factory import ProviderFactory, init_providers

    set_provider_factory_builder(ProviderFactory)

    init_providers(
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        default_embedding_provider=settings.default_embedding_provider,
        default_embedding_model=settings.default_embedding_model,
    )


@pytest.fixture
def test_tenant_id():
    """Return the isolated tenant ID for tests."""
    return TEST_TENANT_ID


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_tenant():
    """
    CRITICAL SAFETY FIXTURE.
    Wipes ALL data for 'integration_test_tenant' before and after every test.
    Prevents data leaks and ensures isolation from 'default' tenant.
    """
    if TEST_TENANT_ID == "default":
        raise RuntimeError("SAFETY ERROR: Cannot run cleanup on 'default' tenant!")

    async def _wipe():
        # 1. Wipe Postgres
        from src.api.deps import _get_async_session_maker

        async with _get_async_session_maker()() as session:
            # Delete dependent tables manually since Cascade might not be set
            await session.execute(
                text(
                    f"DELETE FROM chunks WHERE document_id IN (SELECT id FROM documents WHERE tenant_id = '{TEST_TENANT_ID}')"
                )
            )

            # Delete documents (cascades to chunks, etc via FKs usually, but strictly by tenant_id)
            await session.execute(
                text(f"DELETE FROM documents WHERE tenant_id = '{TEST_TENANT_ID}'")
            )
            await session.execute(
                text(f"DELETE FROM usage_logs WHERE tenant_id = '{TEST_TENANT_ID}'")
            )
            await session.execute(
                text(f"DELETE FROM feedbacks WHERE tenant_id = '{TEST_TENANT_ID}'")
            )
            # Conversation History
            await session.execute(
                text(f"DELETE FROM conversation_summaries WHERE tenant_id = '{TEST_TENANT_ID}'")
            )

            # API Keys Cleanup (Link first, then tenant)
            await session.execute(
                text(f"DELETE FROM api_key_tenants WHERE tenant_id = '{TEST_TENANT_ID}'")
            )

            # Note: We do NOT delete the Tenant record itself to avoid FK constraints on ApiKeyTenant
            # Actually we DO delete the tenant at the end of this block?
            # The original code continued...
            await session.execute(text(f"DELETE FROM tenants WHERE id = '{TEST_TENANT_ID}'"))
            await session.commit()

        # 2. Wipe Neo4j
        from src.amber_platform.composition_root import platform

        neo4j = platform.neo4j_client
        if neo4j:
            await neo4j.connect()
            await neo4j.delete_tenant_data(TEST_TENANT_ID)

        # 3. Wipe Milvus
        # We explicitly use delete_by_tenant, NOT drop_collection
        try:
            from src.core.retrieval.infrastructure.vector_store.milvus import (
                MilvusConfig,
                MilvusVectorStore,
            )
            # We need to connect to the right collection.
            # Standard logic uses "amber_{tenant_id}" or "amber_default"?
            # Check Milvus logic: ActiveVectorCollection determines naming.
            # We assume standard naming "amber_{tenant_id}" for isolation or filters in default.

            # Helper to wipe both strategies just in case
            ms = MilvusVectorStore(
                MilvusConfig(
                    host=os.environ["MILVUS_HOST"],
                    port=os.environ["MILVUS_PORT"],
                    collection_name="document_chunks",  # Default shared
                )
            )
            await ms.delete_by_tenant(TEST_TENANT_ID)

            # Also try dedicated collection if it exists
            ms_dedicated = MilvusVectorStore(
                MilvusConfig(
                    host=os.environ["MILVUS_HOST"],
                    port=os.environ["MILVUS_PORT"],
                    collection_name=f"amber_{TEST_TENANT_ID}",
                )
            )
            # Just try to drop the dedicated collection entirely?
            # Or delete data? Safe to drop dedicated test collection.
            # But we promised NO drop_collection?
            # "We will ban drop_collection in the cleanup fixture" -> meaning on the SHARED one.
            # Dropping the TEST specific collection is fine.
            if await ms_dedicated.drop_collection():
                pass  # Dropped

            await ms.disconnect()
            await ms_dedicated.disconnect()

        except Exception as e:
            # Don't fail cleanup if Milvus is down/empty, but log it
            print(f"Warning during Milvus cleanup: {e}")

    # Run cleanup before test
    await _wipe()
    yield
    # Run cleanup after test
    await _wipe()


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Create test client with enforced Tenant ID."""
    from httpx import ASGITransport, AsyncClient

    # Enforce Tenant ID in headers
    headers = {"X-Tenant-ID": TEST_TENANT_ID}

    # Use app directly (assuming startup events are handled globally or not strictly needed for these tests)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
        yield c


@pytest.fixture
def api_key():
    """Generate and register a test API key LINKED TO TEST TENANT."""
    from src.api.config import settings

    async def _create_key():
        # 1. Generate Key
        raw_key = generate_api_key(prefix="test")
        hashed = hash_api_key(raw_key)

        # 2. Setup Async Engine
        engine = create_async_engine(settings.db.database_url)
        AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as session:
            try:
                # Create Key Record
                key_record = ApiKey(
                    name="Test Integration Key",
                    prefix="test",
                    hashed_key=hashed,
                    last_chars=raw_key[-4:],
                    is_active=True,
                    scopes=["admin", "read", "write"],
                )
                session.add(key_record)
                await session.flush()

                # Create Tenant (if not exists)
                from src.core.tenants.domain.tenant import Tenant

                tenant = await session.get(Tenant, TEST_TENANT_ID)
                if not tenant:
                    tenant = Tenant(id=TEST_TENANT_ID, name="Integration Test Tenant")
                    session.add(tenant)
                    await session.flush()

                # Link Key to Test Tenant
                link = ApiKeyTenant(
                    api_key_id=key_record.id, tenant_id=TEST_TENANT_ID, role="admin"
                )
                session.add(link)

                await session.commit()
            except Exception:
                await session.rollback()
                raise

        await engine.dispose()
        return raw_key

    return asyncio.run(_create_key())
