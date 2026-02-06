"""
Settings Protocol
=================

Defines the settings interface that core/application layers depend on.
Infrastructure provides implementations (e.g., from src.api.config).
"""

from typing import Protocol


class DatabaseSettingsProtocol(Protocol):
    """Protocol for database settings."""

    database_url: str
    pool_size: int
    max_overflow: int
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    milvus_host: str
    milvus_port: int
    redis_url: str


class MinIOSettingsProtocol(Protocol):
    """Protocol for MinIO settings."""

    host: str
    port: int
    root_user: str
    root_password: str
    secure: bool
    bucket_name: str


class ObjectStorageSettingsProtocol(Protocol):
    """Protocol for canonical object storage settings."""

    host: str
    port: int
    access_key: str
    secret_key: str
    secure: bool
    bucket_name: str


class SettingsProtocol(Protocol):
    """
    Protocol defining the settings interface used by core/application layers.

    This allows core to depend on an abstraction rather than src.api.config directly.
    """

    # Application
    app_name: str
    debug: bool
    log_level: str
    secret_key: str

    # Nested settings
    db: DatabaseSettingsProtocol
    object_storage: ObjectStorageSettingsProtocol
    minio: MinIOSettingsProtocol

    # LLM Provider Keys
    openai_api_key: str
    anthropic_api_key: str
    ollama_base_url: str
    default_llm_provider: str | None
    default_llm_model: str | None
    llm_fallback_local: str | None
    llm_fallback_economy: str | None
    llm_fallback_standard: str | None
    llm_fallback_premium: str | None

    # Embedding Configuration
    default_embedding_provider: str | None
    default_embedding_model: str | None
    embedding_fallback_order: str | None
    embedding_dimensions: int | None
