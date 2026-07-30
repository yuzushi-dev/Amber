from pathlib import Path

from src.api.config import CelerySettings, DatabaseSettings, Settings


def test_llm_fallback_settings_present():
    s = Settings()
    assert hasattr(s, "llm_fallback_economy")
    assert hasattr(s, "embedding_fallback_order")


def test_core_requirements_pin_pydantic_settings_without_changing_pydantic():
    requirements = (Path(__file__).parents[2] / "requirements-core.txt").read_text()

    assert "pydantic==2.12.5" in requirements
    assert "pydantic-settings==2.14.2" in requirements


def test_api_settings_loads_tenant_and_parses_provider_key_csv(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "tenant-q2")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEYS", "provider-key-a, , provider-key-b ,")

    settings = Settings()

    assert settings.tenant_id == "tenant-q2"
    assert settings.ollama_cloud_api_keys == ["provider-key-a", "provider-key-b"]


def test_database_settings_load_noncredentialed_connection_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/amber_test")
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql+asyncpg://localhost:5432/amber_app_test")
    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j.invalid:7687")
    monkeypatch.setenv("MILVUS_PORT", "19531")
    monkeypatch.setenv("REDIS_URL", "redis://cache.invalid:6379/15")

    settings = DatabaseSettings()

    assert settings.database_url == "postgresql+asyncpg://localhost:5432/amber_test"
    assert settings.app_database_url == "postgresql+asyncpg://localhost:5432/amber_app_test"
    assert settings.neo4j_uri == "bolt://neo4j.invalid:7687"
    assert settings.milvus_port == 19531
    assert settings.redis_url == "redis://cache.invalid:6379/15"


def test_worker_settings_load_configured_broker_and_result_backend(monkeypatch):
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://worker-broker.invalid:6379/14")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://worker-results.invalid:6379/13")

    settings = CelerySettings()

    assert settings.broker_url == "redis://worker-broker.invalid:6379/14"
    assert settings.result_backend == "redis://worker-results.invalid:6379/13"
