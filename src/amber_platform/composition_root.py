"""
Composition Root
=================

The single place where all dependencies are wired together.
This is the only module that imports from both src.api.config and src.core.

Infrastructure adapters are created here and injected into application services.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

from src.shared.kernel.settings import SettingsProtocol

if TYPE_CHECKING:
    from src.api.config import Settings


# -----------------------------------------------------------------------------
# Settings Provider
# -----------------------------------------------------------------------------

_settings: SettingsProtocol | None = None


def configure_settings(settings: SettingsProtocol) -> None:
    """
    Configure the global settings instance.
    
    Called at application startup (API/worker) to inject the settings.
    This is the only way settings should be provided to core modules.
    """
    global _settings
    _settings = settings


def get_settings() -> SettingsProtocol:
    """
    Get the configured settings instance.
    
    This should be called by core modules instead of importing src.api.config.
    
    Raises:
        RuntimeError: If settings have not been configured.
    """
    if _settings is None:
        raise RuntimeError(
            "Settings not configured. Call configure_settings() at application startup."
        )
    return _settings


@lru_cache
def get_settings_lazy() -> SettingsProtocol:
    """
    Lazy settings accessor that auto-configures from src.api.config if not set.
    
    This provides backward compatibility during the migration period.
    New code should use get_settings() after explicit configuration.
    """
    global _settings
    if _settings is None:
        # Auto-configure from API config for backward compatibility
        from src.api.config import settings as api_settings
        _settings = api_settings
    return _settings


# -----------------------------------------------------------------------------
# Platform Registry (Lifecycle-Managed Clients)
# -----------------------------------------------------------------------------

class PlatformRegistry:
    """
    Holds singleton client instances with explicit lifecycle management.
    
    Usage:
        await platform.initialize()  # At app startup
        client = platform.neo4j_client
        await platform.shutdown()    # At app shutdown
    """
    
    def __init__(self):
        self._neo4j_client = None
        self._minio_client = None
        self._redis_client = None
        self._initialized = False
        
    async def initialize(self) -> None:
        """Initialize all managed clients."""
        if self._initialized:
            return
            
        import logging
        logger = logging.getLogger(__name__)
        
        settings = get_settings_lazy()
        
        # Neo4j
        from src.core.graph.infrastructure.neo4j_client import Neo4jClient
        self._neo4j_client = Neo4jClient(
            uri=settings.db.neo4j_uri,
            user=settings.db.neo4j_user,
            password=settings.db.neo4j_password,
        )
        try:
            await self._neo4j_client.connect()
        except Exception as e:
            logger.warning(f"Neo4j not available at startup: {e}")
        
        # MinIO (sync client, no async init needed)
        from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient
        self._minio_client = MinIOClient(
            host=settings.minio.host,
            port=settings.minio.port,
            access_key=settings.minio.root_user,
            secret_key=settings.minio.root_password,
            secure=settings.minio.secure,
            bucket_name=settings.minio.bucket_name,
        )
        
        # Redis (shared connection for events)
        import redis.asyncio as aioredis
        self._redis_client = aioredis.from_url(settings.db.redis_url)
        
        self._initialized = True
        logger.info("Platform registry initialized")
        
    async def shutdown(self) -> None:
        """Close all managed clients."""
        import logging
        logger = logging.getLogger(__name__)
        
        if self._neo4j_client:
            try:
                await self._neo4j_client.close()
            except Exception as e:
                logger.warning(f"Error closing Neo4j: {e}")
            self._neo4j_client = None
            
        if self._redis_client:
            try:
                await self._redis_client.close()
            except Exception as e:
                logger.warning(f"Error closing Redis: {e}")
            self._redis_client = None

        # Milvus Global Disconnect
        from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore
        await MilvusVectorStore.global_disconnect()
            
        self._initialized = False
        logger.info("Platform registry shutdown complete")
        
    @property
    def neo4j_client(self):
        """Get the managed Neo4j client."""
        if not self._neo4j_client:
            # Lazy fallback for backward compatibility
            from src.core.graph.infrastructure.neo4j_client import Neo4jClient
            settings = get_settings_lazy()
            self._neo4j_client = Neo4jClient(
                uri=settings.db.neo4j_uri,
                user=settings.db.neo4j_user,
                password=settings.db.neo4j_password,
            )
        return self._neo4j_client
        
    @property
    def minio_client(self):
        """Get the managed MinIO client."""
        if not self._minio_client:
            from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient
            settings = get_settings_lazy()
            self._minio_client = MinIOClient(
                host=settings.minio.host,
                port=settings.minio.port,
                access_key=settings.minio.root_user,
                secret_key=settings.minio.root_password,
                secure=settings.minio.secure,
                bucket_name=settings.minio.bucket_name,
            )
        return self._minio_client
        
    @property
    def redis_client(self):
        """Get the managed async Redis client."""
        if not self._redis_client:
            import redis.asyncio as aioredis
            settings = get_settings_lazy()
            self._redis_client = aioredis.from_url(settings.db.redis_url)
        return self._redis_client


# Global platform registry instance
platform = PlatformRegistry()


# -----------------------------------------------------------------------------
# Legacy Client Factories (Deprecated - use platform registry instead)
# -----------------------------------------------------------------------------


def build_neo4j_client():
    """Build a Neo4j client with settings from composition root.
    
    DEPRECATED: Use `platform.neo4j_client` instead.
    """
    return platform.neo4j_client


def build_minio_client():
    """Build a MinIO client with settings from composition root.
    
    DEPRECATED: Use `platform.minio_client` instead.
    """
    return platform.minio_client


def build_milvus_config():
    """Build Milvus configuration from settings."""
    from src.core.retrieval.infrastructure.vector_store.milvus import MilvusConfig
    
    settings = get_settings_lazy()
    return MilvusConfig(
        host=settings.db.milvus_host,
        port=settings.db.milvus_port,
        dimensions=settings.embedding_dimensions or 1536,
    )


def build_vector_store_factory():
    """Build a factory for vector store instances with custom dimensions."""
    from src.core.retrieval.infrastructure.vector_store.milvus import MilvusConfig, MilvusVectorStore

    base = build_milvus_config()

    def make_vector_store(dimensions: int, collection_name: str | None = None):
        config = MilvusConfig(
            host=base.host,
            port=base.port,
            dimensions=dimensions,
            collection_name=collection_name or base.collection_name,
        )
        return MilvusVectorStore(config)

    return make_vector_store


# -----------------------------------------------------------------------------
# Database Session and Unit of Work Factories
# -----------------------------------------------------------------------------


def build_session_factory():
    """
    Return the canonical async session factory from the core database module.
    """
    from src.core.database.session import get_session_maker
    return get_session_maker()


def build_uow_factory():
    """
    Build a Unit of Work factory function.
    
    Returns a factory that creates UoW instances with the given tenant context.
    
    Usage:
        uow_factory = build_uow_factory()
        async with uow_factory(tenant_id, is_super_admin=False) as uow:
            # use uow.session for DB operations
            ...
    """
    from src.core.database.unit_of_work import SqlAlchemyUnitOfWork
    
    session_maker = build_session_factory()
    
    def make_uow(tenant_id: str, is_super_admin: bool = False) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_maker, tenant_id=tenant_id, is_super_admin=is_super_admin)
    
    return make_uow




# -----------------------------------------------------------------------------
# Service Factories
# -----------------------------------------------------------------------------

# @lru_cache # Removed because it now depends on Session (request-scoped)
def build_upload_document_use_case(
    session,
    max_size_bytes: int,
    task_dispatcher=None,
    event_dispatcher=None,
):
    """
    Build UploadDocumentUseCase with concrete infrastructure adapters.
    """
    from src.core.ingestion.application.use_cases_documents import UploadDocumentUseCase
    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import PostgresDocumentRepository
    from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import PostgresTenantRepository
    from src.core.ingestion.infrastructure.uow.postgres_uow import PostgresUnitOfWork
    from src.infrastructure.adapters.celery_dispatcher import CeleryTaskDispatcher
    from src.core.events.dispatcher import EventDispatcher
    from src.infrastructure.adapters.redis_state_publisher import RedisStatePublisher

    vector_store_factory = build_vector_store_factory()

    return UploadDocumentUseCase(
        document_repository=PostgresDocumentRepository(session),
        tenant_repository=PostgresTenantRepository(session),
        unit_of_work=PostgresUnitOfWork(session),
        storage=platform.minio_client,
        max_size_bytes=max_size_bytes,
        graph_client=platform.neo4j_client,
        vector_store=None,
        vector_store_factory=vector_store_factory,
        task_dispatcher=task_dispatcher or CeleryTaskDispatcher(),
        event_dispatcher=event_dispatcher or EventDispatcher(RedisStatePublisher()),
    )

# @lru_cache # Removed because it now depends on Session (request-scoped)
def build_retrieval_service(session=None):
    """
    Build the RetrievalService with configured providers.
    
    Args:
        session: SQLAlchemy AsyncSession (required for DocumentRepository)
        
    Raises:
        ValueError: If session is not provided.
    """
    if not session:
        raise ValueError("Session is required to build RetrievalService")

    from src.core.retrieval.application.retrieval_service import RetrievalConfig, RetrievalService
    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import PostgresDocumentRepository
    from src.core.retrieval.domain.ports.vector_store_port import VectorStorePort
    from src.core.retrieval.infrastructure.vector_store.milvus import MilvusConfig, MilvusVectorStore
    from src.core.graph.infrastructure.neo4j_client import Neo4jClient
    
    settings = get_settings_lazy()
    providers = getattr(settings, "providers", None)
    openai_key = getattr(providers, "openai_api_key", None) or settings.openai_api_key
    anthropic_key = getattr(providers, "anthropic_api_key", None) or settings.anthropic_api_key

    retrieval_config = RetrievalConfig(
        milvus_host=settings.db.milvus_host,
        milvus_port=settings.db.milvus_port,
    )
    
    # Repositories
    document_repo = PostgresDocumentRepository(session)
    
    # Vector Store (using implicit global connection or managed by platform)
    # Ideally checking platform.milvus_client? MilvusVectorStore manages its own connection logic via globally imported pymilvus.
    # We instantiate it here.
    milvus_config = MilvusConfig(
        host=settings.db.milvus_host,
        port=settings.db.milvus_port,
        dimensions=settings.embedding_dimensions or 1536,
    )
    vector_store = MilvusVectorStore(milvus_config)
    
    # Graph Store (Client)
    # Use platform managed one
    neo4j_client = platform.neo4j_client

    return RetrievalService(
        document_repository=document_repo,
        vector_store=vector_store,
        neo4j_client=neo4j_client,
        openai_api_key=openai_key or None,
        anthropic_api_key=anthropic_key or None,
        ollama_base_url=settings.ollama_base_url,
        default_embedding_provider=settings.default_embedding_provider,
        default_embedding_model=settings.default_embedding_model,
        redis_url=settings.db.redis_url,
        config=retrieval_config,
    )


@lru_cache
def build_generation_service():
    """Build the GenerationService with configured providers."""
    from src.core.generation.application.generation_service import GenerationService
    
    settings = get_settings_lazy()
    providers = getattr(settings, "providers", None)
    openai_key = getattr(providers, "openai_api_key", None) or settings.openai_api_key
    anthropic_key = getattr(providers, "anthropic_api_key", None) or settings.anthropic_api_key

    return GenerationService(
        openai_api_key=openai_key or None,
        anthropic_api_key=anthropic_key or None,
        ollama_base_url=settings.ollama_base_url,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
    )


@lru_cache
def build_metrics_collector():
    """Build the MetricsCollector."""
    from src.core.admin_ops.application.metrics.collector import MetricsCollector
    
    settings = get_settings_lazy()
    return MetricsCollector(
        redis_url=settings.db.redis_url,
    )
