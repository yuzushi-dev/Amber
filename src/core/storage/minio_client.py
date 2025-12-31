"""
MinIO Storage Client
====================

Client for interacting with MinIO object storage.
"""

import io
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from src.api.config import settings


class MinIOClient:
    """Wrapper around MinIO client."""

    def __init__(self):
        # We assume MinIO is available at the configured host/port
        # In docker-compose: api depends on minio service
        # But we access it via 'minio' hostname inside docker network
        # Or localhost if running locally with ports exposed
        
        # When running from host (outside docker), use localhost:9000
        # When running from api container, use MILLVUS_HOST (which is 'minio' in docker-compose for MinIO?? No wait)
        
        # Let's check config settings.
        # MINIO_HOST/PORT usually matching the service. 
        # Using settings from config.py
        
        # For this phase implementation, we'll try to use specific env vars or fall back to defaults
        # We need to ensure we can connect.
        
        self.client = Minio(
            endpoint=f"{settings.minio.host}:{settings.minio.port}",
            access_key=settings.minio.root_user,
            secret_key=settings.minio.root_password,
            secure=settings.minio.secure,
        )
        self.bucket_name = settings.minio.bucket_name

    def ensure_bucket_exists(self) -> None:
        """Create the bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            # Handle potential connection issues or permission errors
            raise RuntimeError(f"Failed to check/create bucket: {e}")

    def upload_file(self, object_name: str, data: BinaryIO, length: int, content_type: str = "application/octet-stream") -> None:
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
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            return response.read()
        except S3Error as e:
            raise FileNotFoundError(f"File not found in storage: {object_name}") from e
        finally:
            if 'response' in locals():
                response.close()
                
    def delete_file(self, object_name: str) -> None:
        """Delete a file from storage."""
        self.client.remove_object(self.bucket_name, object_name)
