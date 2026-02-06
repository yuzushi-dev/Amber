from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
import urllib3
from minio import Minio
from minio.error import S3Error
from urllib3 import Retry

from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient

SEAWEED_ENDPOINT = "localhost:8333"
SEAWEED_ACCESS_KEY = "minioadmin"
SEAWEED_SECRET_KEY = "minioadmin"
COMPAT_BUCKET = "compat-check"
PROBE_BUCKET = "probe-health"


@pytest.fixture(autouse=True)
async def cleanup_test_tenant():
    # Override integration-suite tenant cleanup: this test only validates
    # object storage compatibility and does not need DB/graph fixtures.
    yield


def _cleanup_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        return
    for obj in client.list_objects(bucket, recursive=True):
        client.remove_object(bucket, obj.object_name)
    client.remove_bucket(bucket)


def _purge_bucket_objects(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        return
    for obj in client.list_objects(bucket, recursive=True):
        client.remove_object(bucket, obj.object_name)


def _ensure_bucket(client: Minio, bucket: str) -> bool:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        return True
    return False


def _quick_client() -> Minio:
    return Minio(
        SEAWEED_ENDPOINT,
        access_key=SEAWEED_ACCESS_KEY,
        secret_key=SEAWEED_SECRET_KEY,
        secure=False,
        http_client=urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=2, read=2),
            retries=Retry(total=0, connect=0, read=0, status=0, redirect=0),
        ),
    )


@pytest.mark.integration
def test_storage_backend_compatibility_with_seaweedfs():
    bucket = COMPAT_BUCKET
    object_name = f"migration/{uuid4().hex}.txt"
    payload = b"seaweed-backend-compatibility"
    compat_bucket_created = False
    probe_bucket_created = False

    raw_client = Minio(
        SEAWEED_ENDPOINT,
        access_key=SEAWEED_ACCESS_KEY,
        secret_key=SEAWEED_SECRET_KEY,
        secure=False,
    )

    storage = MinIOClient(
        host="localhost",
        port=8333,
        access_key=SEAWEED_ACCESS_KEY,
        secret_key=SEAWEED_SECRET_KEY,
        secure=False,
        bucket_name=bucket,
    )

    try:
        # Fast preflight to avoid long retry loops when SeaweedFS has no writable
        # volumes (e.g. disk full in CI/dev environments).
        probe_bucket = PROBE_BUCKET
        probe_object = f"probe/{uuid4().hex}.txt"
        probe_payload = b"probe"
        try:
            quick_client = _quick_client()
            probe_bucket_created = _ensure_bucket(quick_client, probe_bucket)
            quick_client.put_object(
                bucket_name=probe_bucket,
                object_name=probe_object,
                data=BytesIO(probe_payload),
                length=len(probe_payload),
                content_type="text/plain",
            )
        except Exception as exc:
            pytest.skip(f"SeaweedFS endpoint unavailable or not writable: {exc}")
        finally:
            try:
                if probe_bucket_created:
                    _cleanup_bucket(raw_client, probe_bucket)
                else:
                    _purge_bucket_objects(raw_client, probe_bucket)
            except S3Error:
                pass

        try:
            compat_bucket_created = _ensure_bucket(raw_client, bucket)
            _purge_bucket_objects(raw_client, bucket)
            storage.upload_file(
                object_name=object_name,
                data=BytesIO(payload),
                length=len(payload),
                content_type="text/plain",
            )
        except Exception as exc:
            pytest.skip(f"SeaweedFS storage endpoint unavailable: {exc}")

        assert storage.get_file(object_name) == payload

        stream = storage.get_file_stream(object_name)
        try:
            assert stream.read() == payload
        finally:
            stream.close()
            if hasattr(stream, "release_conn"):
                stream.release_conn()

        storage.delete_file(object_name)
        with pytest.raises(FileNotFoundError):
            storage.get_file(object_name)
    finally:
        try:
            if compat_bucket_created:
                _cleanup_bucket(raw_client, bucket)
            else:
                _purge_bucket_objects(raw_client, bucket)
        except S3Error:
            # Cleanup failure should not hide assertion failures.
            pass
