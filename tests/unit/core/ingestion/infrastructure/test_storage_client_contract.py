from unittest.mock import MagicMock

from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient


def test_storage_client_exposes_required_port_methods():
    client = MinIOClient(
        host="h",
        port=9000,
        access_key="a",
        secret_key="s",
        secure=False,
        bucket_name="b",
    )
    assert hasattr(client, "upload_file")
    assert hasattr(client, "get_file")
    assert hasattr(client, "get_file_stream")
    assert hasattr(client, "delete_file")


def test_delete_file_calls_remove_object():
    client = MinIOClient(
        host="h",
        port=9000,
        access_key="a",
        secret_key="s",
        secure=False,
        bucket_name="b",
    )
    client.client = MagicMock()
    client.delete_file("tenant/doc/file.pdf")
    client.client.remove_object.assert_called_once_with("b", "tenant/doc/file.pdf")
