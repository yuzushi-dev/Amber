import asyncio
import os
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Note: testcontainers removed to favor local development services
# (Postgres :5433, Redis :6379, Milvus :19530, etc.)
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

from src.core.database.session import configure_database
from src.core.graph.domain.ports.graph_client import set_graph_client


class _NullGraphClient:
    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def execute_read(self, query: str, parameters: dict | None = None) -> list[dict]:
        return []

# Configure Database
configure_database(os.environ["DATABASE_URL"])

# Configure Settings
from src.api.config import settings
from src.amber_platform.composition_root import configure_settings
configure_settings(settings)

# Configure Graph Client
from src.core.graph.domain.ports.graph_client import set_graph_client
from src.amber_platform.composition_root import platform
# Ensure platform is initialized (it might be lazy, but Neo4j client access init it)
# Actually, platform.neo4j_client property auto-initializes if settings are configured.
set_graph_client(platform.neo4j_client)

from src.core.ingestion.domain.ports.content_extractor import set_content_extractor
from src.core.ingestion.infrastructure.extraction.fallback_extractor import FallbackContentExtractor
set_content_extractor(FallbackContentExtractor())

from src.core.generation.domain.ports.provider_factory import set_provider_factory_builder
from src.core.generation.infrastructure.providers.factory import ProviderFactory, init_providers
set_provider_factory_builder(ProviderFactory)
init_providers(
    openai_api_key=settings.openai_api_key,
    anthropic_api_key=settings.anthropic_api_key,
    default_llm_provider=settings.default_llm_provider,
    default_llm_model=settings.default_llm_model,
    default_embedding_provider=settings.default_embedding_provider,
    default_embedding_model=settings.default_embedding_model
)



# Other fixtures like integration_db_session can be added here
# if needed for shared integration testing state.

from fastapi.testclient import TestClient
from src.api.main import app


from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant
from src.shared.security import generate_api_key, hash_api_key
from src.api.deps import _async_session_maker

@pytest.fixture
def client(monkeypatch):
    """Create test client."""
    from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService
    monkeypatch.setattr(SparseEmbeddingService, "prewarm", lambda self: False)
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def api_key():
    """Generate and register a test API key using async DB connection."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from src.api.config import settings
    
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
                name="Test Key",
                prefix="test",
                hashed_key=hashed,
                last_chars=raw_key[-4:],
                is_active=True,
                scopes=["admin", "read", "write"]
            )
            session.add(key_record)
            await session.flush() 
            
            # Create Tenant Association (default tenant)
            from src.core.tenants.domain.tenant import Tenant
        
            tenant = await session.get(Tenant, "default")
            if not tenant:
                tenant = Tenant(id="default", name="Default")
                session.add(tenant)
                await session.flush()
                
            # Check if link exists
            result = await session.execute(
                 select(ApiKeyTenant).where(
                     ApiKeyTenant.api_key_id == key_record.id,
                     ApiKeyTenant.tenant_id == "default"
                 )
            )
            if not result.scalars().first():
                link = ApiKeyTenant(
                    api_key_id=key_record.id,
                    tenant_id="default",
                    role="admin"
                )
                session.add(link)
            
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    
    await engine.dispose()
    return raw_key
