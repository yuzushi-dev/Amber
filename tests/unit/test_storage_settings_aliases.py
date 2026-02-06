from src.api.config import Settings


def test_object_storage_aliases_fall_back_to_minio_env(monkeypatch):
    monkeypatch.delenv("OBJECT_STORAGE_HOST", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_PORT", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_ACCESS_KEY", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_SECRET_KEY", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_SECURE", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_BUCKET_NAME", raising=False)

    monkeypatch.setenv("MINIO_HOST", "minio-legacy")
    monkeypatch.setenv("MINIO_PORT", "9100")
    monkeypatch.setenv("MINIO_ROOT_USER", "minioadmin")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "miniosecret")
    monkeypatch.setenv("MINIO_SECURE", "true")
    monkeypatch.setenv("MINIO_BUCKET_NAME", "documents")

    settings = Settings()
    assert settings.object_storage.host == "minio-legacy"
    assert settings.object_storage.port == 9100
    assert settings.object_storage.access_key == "minioadmin"
    assert settings.object_storage.secret_key == "miniosecret"
    assert settings.object_storage.secure is True
    assert settings.object_storage.bucket_name == "documents"


def test_minio_view_reads_object_storage_env_for_backward_compat(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_HOST", "seaweed-s3")
    monkeypatch.setenv("OBJECT_STORAGE_PORT", "8333")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "seaweed-access")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "seaweed-secret")
    monkeypatch.setenv("OBJECT_STORAGE_SECURE", "false")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET_NAME", "documents")

    monkeypatch.delenv("MINIO_HOST", raising=False)
    monkeypatch.delenv("MINIO_PORT", raising=False)
    monkeypatch.delenv("MINIO_ROOT_USER", raising=False)
    monkeypatch.delenv("MINIO_ROOT_PASSWORD", raising=False)
    monkeypatch.delenv("MINIO_SECURE", raising=False)
    monkeypatch.delenv("MINIO_BUCKET_NAME", raising=False)

    settings = Settings()
    assert settings.minio.host == "seaweed-s3"
    assert settings.minio.port == 8333
    assert settings.minio.root_user == "seaweed-access"
    assert settings.minio.root_password == "seaweed-secret"
    assert settings.minio.secure is False
    assert settings.minio.bucket_name == "documents"
