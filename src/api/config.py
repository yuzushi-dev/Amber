"""
Application Configuration
=========================

Centralized configuration management using Pydantic Settings.
Environment variables take precedence over config file values.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database connection settings."""

    # PostgreSQL
    database_url: str = Field(
        default="postgresql+asyncpg://graphrag:graphrag@localhost:5432/graphrag",
        alias="DATABASE_URL",
        description="PostgreSQL connection URL",
    )
    pool_size: int = Field(default=20, description="SQLAlchemy pool size")
    max_overflow: int = Field(default=20, description="SQLAlchemy pool max overflow")

    # Neo4j
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI", description="Neo4j connection URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER", description="Neo4j username")
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD", description="Neo4j password")

    # Milvus
    milvus_host: str = Field(default="localhost", alias="MILVUS_HOST", description="Milvus host")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT", description="Milvus port")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL", description="Redis connection URL")


class CelerySettings(BaseSettings):
    """Celery worker settings."""

    broker_url: str = Field(
        default="redis://localhost:6379/1",
        alias="CELERY_BROKER_URL",
        description="Celery broker URL",
    )
    result_backend: str = Field(
        default="redis://localhost:6379/2",
        alias="CELERY_RESULT_BACKEND",
        description="Celery result backend URL",
    )


class RateLimitSettings(BaseSettings):
    """Rate limiting configuration."""

    requests_per_minute: int = Field(default=60, description="Max requests per minute")
    requests_per_hour: int = Field(default=1000, description="Max requests per hour")
    queries_per_minute: int = Field(default=20, description="Max queries per minute")
    uploads_per_hour: int = Field(default=50, description="Max uploads per hour")


class UploadSettings(BaseSettings):
    """Upload configuration."""

    max_size_mb: int = Field(default=100, description="Max upload size in MB")
    max_concurrent: int = Field(default=5, description="Max concurrent ingestions")


class MinIOSettings(BaseSettings):
    """MinIO object storage settings."""

    model_config = SettingsConfigDict(env_prefix="MINIO_", extra="ignore")

    host: str = Field(default="localhost", description="MinIO host")
    port: int = Field(default=9000, description="MinIO API port")
    root_user: str = Field(default="", description="MinIO access key")
    root_password: str = Field(default="", description="MinIO secret key")
    secure: bool = Field(default=False, description="Use HTTPS")
    bucket_name: str = Field(default="documents", description="Document storage bucket")


class Settings(BaseSettings):
    """
    Main application settings.

    Loads configuration from:
    1. Environment variables (highest priority)
    2. config/settings.yaml file
    3. Default values (lowest priority)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="Amber", description="Application name")
    app_version: str = Field(default="0.0.1-alpha", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # API
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    cors_origins: list[str] = Field(default_factory=list, description="Allowed CORS origins")

    # Security
    secret_key: str = Field(
        default="",
        description="Secret key for hashing",
    )

    # Tenant
    tenant_id: str = Field(default="default", description="Default tenant ID")

    # Nested settings (loaded separately)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    celery: CelerySettings = Field(default_factory=CelerySettings)
    rate_limits: RateLimitSettings = Field(default_factory=RateLimitSettings)
    uploads: UploadSettings = Field(default_factory=UploadSettings)
    minio: MinIOSettings = Field(default_factory=MinIOSettings)

    # LLM Provider Keys
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    ollama_base_url: str = Field(default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL", description="Ollama base URL")
    default_llm_provider: str | None = Field(default=None, alias="DEFAULT_LLM_PROVIDER", description="Default LLM provider")
    default_llm_model: str | None = Field(default=None, alias="DEFAULT_LLM_MODEL", description="Default LLM model")

    # Embedding Provider Configuration
    default_embedding_provider: str | None = Field(default=None, alias="DEFAULT_EMBEDDING_PROVIDER", description="Default embedding provider (openai, ollama, local)")
    default_embedding_model: str | None = Field(default=None, alias="DEFAULT_EMBEDDING_MODEL", description="Default embedding model")
    embedding_dimensions: int | None = Field(default=None, alias="EMBEDDING_DIMENSIONS", description="Embedding dimensions (auto-detected if not set)")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v_upper

    @field_validator("cors_origins", mode="before")
    @classmethod
    def normalize_cors_origins(cls, v: Any) -> list[str]:
        """Allow comma-separated or list-based CORS origin configuration."""
        if v is None:
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return list(v)

    @classmethod
    def load_yaml_config(cls, config_path: Path | None = None) -> dict[str, Any]:
        """Load configuration from YAML file."""
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
        return {}


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings.

    Returns:
        Settings: Application settings instance
    """
    settings = Settings()

    try:
        yaml_config = Settings.load_yaml_config()

        # Apply Rate Limits from YAML (no env vars usually)
        if "rate_limits" in yaml_config:
            settings.rate_limits = RateLimitSettings(**yaml_config["rate_limits"])

        # Apply DB pool settings from YAML (preserve existing URL)
        if "db" in yaml_config:
            db_config = yaml_config["db"]
            if "pool_size" in db_config:
                settings.db.pool_size = db_config["pool_size"]
            if "max_overflow" in db_config:
                settings.db.max_overflow = db_config["max_overflow"]

        # Apply API settings from YAML
        api_config = yaml_config.get("api", {})
        if "cors_origins" in api_config:
            settings.cors_origins = Settings.normalize_cors_origins(api_config["cors_origins"])

    except Exception:
        # Fallback to defaults/env if YAML fails
        pass

    return settings


# Convenience access
settings = get_settings()
