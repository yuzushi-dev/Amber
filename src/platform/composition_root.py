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
# Client Factories
# -----------------------------------------------------------------------------


def build_neo4j_client():
    """Build a Neo4j client with settings from composition root."""
    from src.core.graph.neo4j_client import Neo4jClient
    
    settings = get_settings_lazy()
    return Neo4jClient(
        uri=settings.db.neo4j_uri,
        user=settings.db.neo4j_user,
        password=settings.db.neo4j_password,
    )


def build_minio_client():
    """Build a MinIO client with settings from composition root."""
    from src.core.storage.storage_client import MinIOClient
    
    settings = get_settings_lazy()
    return MinIOClient(
        host=settings.minio.host,
        port=settings.minio.port,
        access_key=settings.minio.root_user,
        secret_key=settings.minio.root_password,
        secure=settings.minio.secure,
        bucket_name=settings.minio.bucket_name,
    )


def build_milvus_config():
    """Build Milvus configuration from settings."""
    from src.core.vector_store.milvus import MilvusConfig
    
    settings = get_settings_lazy()
    return MilvusConfig(
        host=settings.db.milvus_host,
        port=settings.db.milvus_port,
        dimensions=settings.embedding_dimensions or 1536,
    )
