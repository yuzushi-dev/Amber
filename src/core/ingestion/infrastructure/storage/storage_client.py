"""
MinIO Storage Client
====================

Client for interacting with MinIO object storage.
"""

import logging
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from src.shared.kernel.runtime import get_settings

# ... imports
# logger setup later
logger = logging.getLogger(__name__)


class MinIOClient:
    """Wrapper around MinIO client."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
        bucket_name: str | None = None,
    ):
        """
        Initialize MinIO client.

        Args:
            host: MinIO host. If None, reads from composition root.
            port: MinIO port. If None, reads from composition root.
            access_key: Access key. If None, reads from composition root.
            secret_key: Secret key. If None, reads from composition root.
            secure: Use HTTPS. If None, reads from composition root.
            bucket_name: Bucket name. If None, reads from composition root.
        """
        if any(v is None for v in [host, port, access_key, secret_key, secure, bucket_name]):
            settings = get_settings()
            storage_settings = (
                settings.object_storage if hasattr(settings, "object_storage") else settings.minio
            )
            host = host if host is not None else storage_settings.host
            port = port if port is not None else storage_settings.port
            access_key = (
                access_key
                if access_key is not None
                else getattr(
                    storage_settings, "access_key", getattr(storage_settings, "root_user", "")
                )
            )
            secret_key = (
                secret_key
                if secret_key is not None
                else getattr(
                    storage_settings, "secret_key", getattr(storage_settings, "root_password", "")
                )
            )
            secure = secure if secure is not None else storage_settings.secure
            bucket_name = bucket_name if bucket_name is not None else storage_settings.bucket_name

        self.client = Minio(
            endpoint=f"{host}:{port}",
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self.bucket_name = bucket_name
        logger.debug(
            f"MinIO Client initialized. Endpoint: {host}:{port}, Bucket: {self.bucket_name}"
        )

    def ensure_bucket_exists(self) -> None:
        """Create the bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            # Handle potential connection issues or permission errors
            raise RuntimeError(f"Failed to check/create bucket: {e}") from e

    def upload_file(
        self,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> None:
        """
        Upload a file-like object to MinIO.

        Args:
            object_name: The path/name of the object in the bucket
            data: Binary I/O stream
            length: Size of the data
            content_type: MIME type
        """
        self.ensure_bucket_exists()
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=object_name,
            data=data,
            length=length,
            content_type=content_type,
        )

    def get_file(self, object_name: str) -> bytes:
        """
        Download a file's content as bytes.

        Args:
            object_name: The path/name of the object

        Returns:
            bytes: The file content
        """
        logger.info(f"DEBUG: MinIO Fetching {object_name} from {self.bucket_name}")
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            return response.read()
        except S3Error as e:
            msg = f"Storage Error: {e.code} - {e.message}. Resource: {object_name}"
            # Preserve original traceback
            raise FileNotFoundError(msg) from e
        finally:
            if "response" in locals():
                response.close()

    def get_file_stream(self, object_name: str):
        """
        Get a file stream from MinIO.

        Args:
            object_name: The path/name of the object

        Returns:
            urllib3.response.HTTPResponse: The file stream
        """
        logger.info(f"DEBUG: MinIO Stream Fetching {object_name} from {self.bucket_name}")
        try:
            return self.client.get_object(self.bucket_name, object_name)
        except S3Error as e:
            msg = f"Storage Error: {e.code} - {e.message}. Resource: {object_name}"
            # Preserve original traceback
            raise FileNotFoundError(msg) from e

    def delete_file(self, object_name: str) -> None:
        """Delete a file from storage."""
        self.client.remove_object(self.bucket_name, object_name)
