from src.core.graph.infrastructure.neo4j_client import Neo4jClient
from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient
from src.shared.kernel.runtime import _reset_for_tests, configure_settings


class FakeDb:
    database_url = "postgresql+asyncpg://user:pass@localhost/db"
    pool_size = 5
    max_overflow = 10
    neo4j_uri = "bolt://localhost:7687"
    neo4j_user = "neo4j"
    neo4j_password = "pass"
    milvus_host = "localhost"
    milvus_port = 19530
    redis_url = "redis://localhost:6379/0"


class FakeMinio:
    host = "minio"
    port = 9000
    root_user = "minio"
    root_password = "minio"
    secure = False
    bucket_name = "amber"


class FakeObjectStorage:
    host = "seaweed-s3"
    port = 8333
    access_key = "seaweed"
    secret_key = "secret"
    secure = False
    bucket_name = "amber-object"


class FakeSettings:
    app_name = "amber"
    debug = False
    log_level = "INFO"
    secret_key = "secret"
    db = FakeDb()
    object_storage = FakeObjectStorage()
    minio = FakeMinio()
    openai_api_key = ""
    anthropic_api_key = ""
    ollama_base_url = ""
    default_llm_provider = None
    default_llm_model = None
    default_embedding_provider = None
    default_embedding_model = None
    embedding_dimensions = None


class FakeLegacySettings:
    app_name = "amber"
    debug = False
    log_level = "INFO"
    secret_key = "secret"
    db = FakeDb()
    minio = FakeMinio()
    openai_api_key = ""
    anthropic_api_key = ""
    ollama_base_url = ""
    default_llm_provider = None
    default_llm_model = None
    default_embedding_provider = None
    default_embedding_model = None
    embedding_dimensions = None


def setup_function():
    _reset_for_tests()


def test_neo4j_client_uses_shared_settings():
    configure_settings(FakeSettings())
    client = Neo4jClient()
    assert client.uri == FakeDb.neo4j_uri
    assert client.user == FakeDb.neo4j_user
    assert client.password == FakeDb.neo4j_password


def test_minio_client_uses_shared_settings():
    configure_settings(FakeSettings())
    client = MinIOClient()
    assert client.bucket_name == FakeObjectStorage.bucket_name


def test_minio_client_falls_back_to_legacy_minio_settings():
    configure_settings(FakeLegacySettings())
    client = MinIOClient()
    assert client.bucket_name == FakeMinio.bucket_name
