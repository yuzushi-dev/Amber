import asyncio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Note: testcontainers removed to favor local development services
# (Postgres :5433, Redis :6379, Milvus :19530, etc.)

@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# Other fixtures like integration_db_session can be added here
# if needed for shared integration testing state.

from fastapi.testclient import TestClient
from src.api.main import app


from src.core.models.api_key import ApiKey, ApiKeyTenant
from src.shared.security import generate_api_key, hash_api_key
from src.api.deps import _async_session_maker

@pytest.fixture
def client():
    """Create test client."""
    from fastapi.testclient import TestClient
    from src.api.main import app
    return TestClient(app)


@pytest.fixture
def api_key():
    """Generate and register a test API key using sync DB connection."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.api.config import settings
    
    # 1. Generate Key
    raw_key = generate_api_key(prefix="test")
    hashed = hash_api_key(raw_key)
    
    # 2. Setup Sync Engine
    # Use the configured URL but remove +asyncpg driver to use default (psycopg2)
    db_url = settings.db.database_url.replace("+asyncpg", "")
    
    # Force host/port if needed, but we rely on the env var passed to pytest (DATABASE_URL)
    # properly configuring settings.
    
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
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
        session.flush() # get ID
        
        # Create Tenant Association (default tenant)
        from src.core.models.tenant import Tenant
        tenant = session.get(Tenant, "default")
        if not tenant:
            tenant = Tenant(id="default", name="Default")
            session.add(tenant)
            session.flush()
            
        link = ApiKeyTenant(
            api_key_id=key_record.id,
            tenant_id="default",
            role="admin"
        )
        session.add(link)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        
    return raw_key
