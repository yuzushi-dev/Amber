
import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock, AsyncMock, patch
from src.api.main import app
from src.amber_platform.composition_root import platform
neo4j_client = platform.neo4j_client


@pytest.fixture
def api_key() -> str:
    return "amber-dev-key-2024"

# Removed local test_client fixture to use global 'client' from conftest which has tenant headers
# If explicit mocks were needed, they should be applied to the global or via autouse patches


class TestSimilarity:
    
    @pytest.mark.asyncio
    async def test_similarity_creation(
        self,
        client: AsyncClient, # Use global client fixture from conftest which has X-Tenant-ID
        api_key: str
    ):
        # Patch ApiKeyService to allow auth
        mock_key_service_cls = patch("src.core.admin_ops.application.api_key_service.ApiKeyService").start()
        mock_auth_service = mock_key_service_cls.return_value
        
        mock_key = MagicMock()
        mock_key.id = "test-key-id"
        mock_key.name = "Test Key"
        mock_key.scopes = ["admin"]
        # Use the same constant as conftest, or just the string literal
        test_tenant = "integration_test_tenant" 
        mock_key.tenants = [MagicMock(id=test_tenant)]
        
        mock_auth_service.validate_key = AsyncMock(return_value=mock_key)

        # ----------------------------------------------------------------------
        # GLOBAL MOCKS (Moved out of create_pdf so we can clean them up)
        # ----------------------------------------------------------------------
        from src.amber_platform.composition_root import platform
        
        # 1. MinIO
        mock_storage = MagicMock()
        mock_storage.upload_file.return_value = "mock/path"
        mock_storage.get_file.return_value = b"content"
        original_minio = platform._minio_client
        platform._minio_client = mock_storage
        
        # 2. Redis
        mock_redis = AsyncMock()
        original_redis = platform._redis_client
        platform._redis_client = mock_redis
        
        # 3. Neo4j
        mock_neo4j = MagicMock()
        mock_neo4j.connect = AsyncMock()
        mock_neo4j.close = AsyncMock()
        mock_neo4j.execute_write = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(return_value=[{"count": 5}]) 
        original_neo4j = platform._neo4j_client # Not typically used but good practice
        platform._neo4j_client = mock_neo4j

        # 4. Celery Dispatcher & Tasks
        # Force eager (needs to be done globally or once)
        from src.workers.celery_app import celery_app
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        
        patch_process = patch("src.workers.tasks.process_communities").start()
        patch_dispatch = patch("src.infrastructure.adapters.celery_dispatcher.CeleryTaskDispatcher.dispatch", new_callable=AsyncMock).start()
        mock_dispatch = patch_dispatch

        try:
            import uuid
            run_id = str(uuid.uuid4())
            # Create two documents with similar but not identical content to avoid deduplication
            # Doc 1
            text_1 = f"The quick brown fox jumps over the lazy dog. {run_id} " * 20
            # Doc 2 (Semantically similar)
            text_2 = f"A fast brown fox leaps over a lazy dog. {run_id} " * 20
            
            async def create_pdf(text, filename):
                files = {"file": (filename, b"%PDF-1.4 dummy content", "application/pdf")}
                
                print(f"Uploading {filename}...")
                response = await client.post(
                    "/v1/documents",
                    headers={"X-API-Key": api_key},
                    files=files
                )
                assert response.status_code == 202
                return response.json()["document_id"]

            # Upload Doc 1
            doc_id_1 = await create_pdf(text_1, "doc1.pdf")
            
            # Wait for Doc 1
            for _ in range(5):
                 await asyncio.sleep(0.1)
            
            resp = await client.get(f"/v1/documents/{doc_id_1}", headers={"X-API-Key": api_key})
            assert resp.json()["status"] == "ingested"


            # Upload Doc 2
            doc_id_2 = await create_pdf(text_2, "doc2.pdf")
            
            resp = await client.get(f"/v1/documents/{doc_id_2}", headers={"X-API-Key": api_key})
            assert resp.status_code == 200
            assert resp.json()["status"] == "ingested"

        finally:
            # Restore original platform clients
            platform._minio_client = original_minio
            platform._redis_client = original_redis
            platform._neo4j_client = original_neo4j # Restore check
            
            patch.stopall() # Stops KeyService, Process, Dispatch patches
