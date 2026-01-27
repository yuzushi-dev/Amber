import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.session import get_session_maker

# Mock dependencies that might be missing in the host environment
# NOTE: Do NOT mock packages that are actually installed (pydantic, fastapi, etc.)
# Only mock optional/heavy dependencies that may not be installed in test environment


# ============================================================================
# Tiktoken Mock - Returns realistic token counts
# ============================================================================
class MockTiktokenEncoding:
    """Mock tiktoken encoding that returns realistic token counts."""

    def encode(self, text: str):
        """Estimate tokens as ~4 chars per token (industry standard approximation)."""
        if not text:
            return []
        # Return a list with length = estimated token count
        estimated_tokens = max(1, len(text) // 4)
        return list(range(estimated_tokens))

    def decode(self, tokens):
        """Decode tokens back to approximate text length."""
        if not tokens:
            return ""
        # Return placeholder text of approximate length
        return "x" * (len(tokens) * 4)


class MockTiktoken:
    """Mock tiktoken module."""

    def get_encoding(self, encoding_name: str):
        return MockTiktokenEncoding()

    def encoding_for_model(self, model: str):
        return MockTiktokenEncoding()


tiktoken_mock = MockTiktoken()


# ============================================================================
# Minio Mock - With proper submodule support
# ============================================================================
minio_mock = MagicMock()
minio_mock.error = MagicMock()
minio_mock.error.S3Error = Exception  # Make S3Error a real exception class


# ============================================================================
# List of modules to mock
# ============================================================================
mock_modules = [
    "neo4j",
    "pymilvus",
    "cdlib",
    "leidenalg",
    "igraph",
    "sentence_transformers",
    "flashrank",
    "numpy",
    "pandas",
    "scipy",
    "sklearn"
]

for module_name in mock_modules:
    try:
        __import__(module_name)
    except ImportError:
        pass

    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()


# Set up tiktoken with realistic mock
if "tiktoken" not in sys.modules:
    sys.modules["tiktoken"] = tiktoken_mock


# Set up minio with submodule support
# if "minio" not in sys.modules:
#     sys.modules["minio"] = minio_mock
#     sys.modules["minio.error"] = minio_mock.error


# ============================================================================
# Neo4j specific mocks
# ============================================================================
import neo4j  # noqa: E402

# neo4j.AsyncGraphDatabase = MagicMock()
# neo4j.AsyncDriver = MagicMock()
# neo4j.AsyncSession = MagicMock()


# ============================================================================
# Database Fixtures
# ============================================================================
@pytest.fixture
async def db_session() -> AsyncSession:
    """
    Yields an async database session for testing.
    Rolls back transaction after test.
    """
    # Create session
    async_session = get_session_maker()

    async with async_session() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest.fixture(autouse=True)
async def cleanup_application_state():
    """
    Global teardown to reset singleton states and close connections
    to prevent async loop mismatch errors and resource leaks.
    
    NOTE: We explicitly set variables to None instead of calling 
    close()/shutdown() methods because those methods often try to 
    clean up resources bound to a previous (now closed) event loop,
    causing 'RuntimeError: Event loop is closed'.
    By setting to None, we force re-initialization in the next test's loop.
    """
    yield
    
    # 1. Reset Rate Limiter
    try:
        import src.api.middleware.rate_limit as rate_limit_module
        rate_limit_module._rate_limiter = None
    except ImportError:
        pass

    # 2. Reset Database Session Maker and Engine
    try:
        import src.api.deps as deps_module
        deps_module._async_session_maker = None
        
        import src.core.database.session as session_mod
        # Force reset without await engine.dispose() to avoid loop conflicts
        session_mod._engine = None
        session_mod._async_session_maker = None
    except ImportError:
        pass

    # 3. Reset Platform (Neo4j, Redis, etc.)
    try:
        from src.amber_platform.composition_root import platform
        # Reset internal state directly
        platform._neo4j_client = None
        platform._redis_client = None
        platform._minio_client = None
        platform._graph_extractor = None
        platform._content_extractor = None
        platform._initialized = False
        
        # Reset external registries
        from src.core.graph.domain.ports.graph_client import set_graph_client
        set_graph_client(None)
        
        from src.core.generation.domain.ports.provider_factory import set_provider_factory_builder, set_provider_factory
        set_provider_factory_builder(None)
        set_provider_factory(None)
        
    except (ImportError, Exception):
        pass

