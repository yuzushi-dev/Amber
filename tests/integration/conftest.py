import pytest
import os
import asyncio
from testcontainers.postgres import PostgresContainer
from testcontainers.neo4j import Neo4jContainer
from testcontainers.minio import MinioContainer
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Only import if we are running integration tests
# This prevents testcontainers from being a hard dependency for unit tests

@pytest.fixture(scope="session")
def postgres_container():
    """Spin up a Postgres container for the session."""
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres

@pytest.fixture(scope="session")
def neo4j_container():
    """Spin up a Neo4j container for the session."""
    with Neo4jContainer("neo4j:5.15.0") as neo4j:
        yield neo4j

@pytest.fixture(scope="session")
def minio_container():
    """Spin up a Minio container for the session."""
    with MinioContainer("minio/minio:RELEASE.2023-12-02T10-51-33Z") as minio:
        yield minio

@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def integration_db_session(postgres_container):
    """
    Yields an async database session connected to the test container.
    """
    db_url = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with engine.begin() as conn:
        # Here we would run alembic migrations if needed
        # For now, we just yield the session
        pass

    async with async_session() as session:
        yield session
        await session.rollback()
