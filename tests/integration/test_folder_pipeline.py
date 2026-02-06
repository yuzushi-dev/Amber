"""
Integration Tests for Folder Pipeline
======================================

Tests for folder CRUD operations and document-folder associations:
- Creating folders
- Listing folders
- Deleting folders (with document unfiling)
- Moving documents between folders
"""

import uuid

import pytest

from src.core.ingestion.domain.document import Document
from src.core.state.machine import DocumentStatus


@pytest.mark.asyncio
class TestFolderCRUD:
    """Tests for folder create, read, delete operations."""

    async def test_create_folder(self, client, api_key):
        """Should create a new folder."""
        folder_name = f"test-folder-{uuid.uuid4().hex[:8]}"
        response = await client.post(
            "/v1/folders",
            json={"name": folder_name},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 201, (
            f"Expected 201, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data["name"] == folder_name
        assert "id" in data
        assert "tenant_id" in data
        assert "created_at" in data

    async def test_list_folders(self, client, api_key):
        """Should list all folders for the tenant."""
        # Create a folder first
        folder_name = f"list-test-{uuid.uuid4().hex[:8]}"
        create_response = await client.post(
            "/v1/folders",
            json={"name": folder_name},
            headers={"X-API-Key": api_key},
        )
        assert create_response.status_code == 201

        # List folders
        response = await client.get(
            "/v1/folders",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert isinstance(data, list)
        # Check that our folder is in the list
        folder_names = [f["name"] for f in data]
        assert folder_name in folder_names

    async def test_delete_folder(self, client, api_key):
        """Should delete a folder."""
        # Create a folder
        folder_name = f"delete-test-{uuid.uuid4().hex[:8]}"
        create_response = await client.post(
            "/v1/folders",
            json={"name": folder_name},
            headers={"X-API-Key": api_key},
        )
        assert create_response.status_code == 201
        folder_id = create_response.json()["id"]

        # Delete the folder
        delete_response = await client.delete(
            f"/v1/folders/{folder_id}",
            headers={"X-API-Key": api_key},
        )
        assert delete_response.status_code == 204, (
            f"Expected 204, got {delete_response.status_code}: {delete_response.text}"
        )

        # Verify folder no longer exists in list
        list_response = await client.get(
            "/v1/folders",
            headers={"X-API-Key": api_key},
        )
        assert list_response.status_code == 200
        folder_ids = [f["id"] for f in list_response.json()]
        assert folder_id not in folder_ids

    async def test_delete_nonexistent_folder(self, client, api_key):
        """Should return 404 for non-existent folder."""
        fake_id = str(uuid.uuid4())
        response = await client.delete(
            f"/v1/folders/{fake_id}",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 404

    async def test_create_folder_validation(self, client, api_key):
        """Should validate folder name."""
        # Empty name
        response = await client.post(
            "/v1/folders",
            json={"name": ""},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 422

        # Missing name
        response = await client.post(
            "/v1/folders",
            json={},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestDocumentFolderAssignment:
    """Tests for moving documents between folders."""

    async def test_move_document_to_folder(self, client, api_key, db_session, test_tenant_id):
        """Should move a document to a folder."""
        # Seed a document
        doc_id = f"doc_{uuid.uuid4().hex[:16]}"
        doc = Document(
            id=doc_id,
            tenant_id=test_tenant_id,
            filename="test_move.txt",
            status=DocumentStatus.READY,
            content_hash=uuid.uuid4().hex,
            storage_path="test/path/move.txt",
        )
        db_session.add(doc)
        await db_session.commit()
        # Create a folder
        folder_name = f"doc-move-test-{uuid.uuid4().hex[:8]}"
        folder_response = await client.post(
            "/v1/folders",
            json={"name": folder_name},
            headers={"X-API-Key": api_key},
        )
        assert folder_response.status_code == 201
        folder_id = folder_response.json()["id"]

        # Get list of documents to find one we can test with
        docs_response = await client.get(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        assert docs_response.status_code == 200
        documents = docs_response.json()

        if not documents:
            pytest.fail("Document seeding failed - list is empty")

        doc_id = documents[0]["id"]

        # Move document to folder
        update_response = await client.patch(
            f"/v1/documents/{doc_id}",
            json={"folder_id": folder_id},
            headers={"X-API-Key": api_key},
        )
        assert update_response.status_code == 200, (
            f"Expected 200, got {update_response.status_code}: {update_response.text}"
        )

        # Verify document has folder assigned
        doc_response = await client.get(
            f"/v1/documents/{doc_id}",
            headers={"X-API-Key": api_key},
        )
        assert doc_response.status_code == 200
        doc_data = doc_response.json()
        assert doc_data.get("folder_id") == folder_id

    async def test_unfile_document(self, client, api_key, db_session, test_tenant_id):
        """Should remove document from folder when folder_id is empty string."""
        # Seed a document
        doc_id = f"doc_{uuid.uuid4().hex[:16]}"
        doc = Document(
            id=doc_id,
            tenant_id=test_tenant_id,
            filename="test_unfile.txt",
            status=DocumentStatus.READY,
            content_hash=uuid.uuid4().hex,
            storage_path="test/path/unfile.txt",
        )
        db_session.add(doc)
        await db_session.commit()
        # First create folder and assign a document
        folder_name = f"unfile-test-{uuid.uuid4().hex[:8]}"
        folder_response = await client.post(
            "/v1/folders",
            json={"name": folder_name},
            headers={"X-API-Key": api_key},
        )
        assert folder_response.status_code == 201
        folder_id = folder_response.json()["id"]

        # Get a document
        docs_response = await client.get(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        assert docs_response.status_code == 200
        documents = docs_response.json()

        if not documents:
            pytest.fail("Document seeding failed")

        doc_id = documents[0]["id"]

        # Assign to folder
        await client.patch(
            f"/v1/documents/{doc_id}",
            json={"folder_id": folder_id},
            headers={"X-API-Key": api_key},
        )

        # Unfile document (send empty string to clear folder_id)
        update_response = await client.patch(
            f"/v1/documents/{doc_id}",
            json={"folder_id": ""},
            headers={"X-API-Key": api_key},
        )
        assert update_response.status_code == 200

        # Verify document is unfiled
        doc_response = await client.get(
            f"/v1/documents/{doc_id}",
            headers={"X-API-Key": api_key},
        )
        assert doc_response.status_code == 200
        doc_data = doc_response.json()
        assert doc_data.get("folder_id") is None

    async def test_delete_folder_unfiles_documents(
        self, client, api_key, db_session, test_tenant_id
    ):
        """Deleting a folder should unfile its documents."""
        # Seed a document
        doc_id = f"doc_{uuid.uuid4().hex[:16]}"
        doc = Document(
            id=doc_id,
            tenant_id=test_tenant_id,
            filename="test_cascade.txt",
            status=DocumentStatus.READY,
            content_hash=uuid.uuid4().hex,
            storage_path="test/path/cascade.txt",
        )
        db_session.add(doc)
        await db_session.commit()
        # Create folder
        folder_name = f"cascade-test-{uuid.uuid4().hex[:8]}"
        folder_response = await client.post(
            "/v1/folders",
            json={"name": folder_name},
            headers={"X-API-Key": api_key},
        )
        assert folder_response.status_code == 201
        folder_id = folder_response.json()["id"]

        # Get a document
        docs_response = await client.get(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        assert docs_response.status_code == 200
        documents = docs_response.json()

        if not documents:
            pytest.fail("Document seeding failed")

        doc_id = documents[0]["id"]

        # Assign to folder
        await client.patch(
            f"/v1/documents/{doc_id}",
            json={"folder_id": folder_id},
            headers={"X-API-Key": api_key},
        )

        # Delete the folder
        delete_response = await client.delete(
            f"/v1/folders/{folder_id}",
            headers={"X-API-Key": api_key},
        )
        assert delete_response.status_code == 204

        # Verify document is now unfiled
        doc_response = await client.get(
            f"/v1/documents/{doc_id}",
            headers={"X-API-Key": api_key},
        )
        assert doc_response.status_code == 200
        doc_data = doc_response.json()
        assert doc_data.get("folder_id") is None

    async def test_move_document_to_nonexistent_folder(
        self, client, api_key, db_session, test_tenant_id
    ):
        """Should return 404 when moving to non-existent folder."""
        # Seed a document
        doc_id = f"doc_{uuid.uuid4().hex[:16]}"
        doc = Document(
            id=doc_id,
            tenant_id=test_tenant_id,
            filename="test_404.txt",
            status=DocumentStatus.READY,
            content_hash=uuid.uuid4().hex,
            storage_path="test/path/404.txt",
        )
        db_session.add(doc)
        await db_session.commit()
        # Get a document
        docs_response = await client.get(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        assert docs_response.status_code == 200
        documents = docs_response.json()

        if not documents:
            pytest.fail("Document seeding failed")

        doc_id = documents[0]["id"]
        fake_folder_id = str(uuid.uuid4())

        # Try to move to fake folder
        update_response = await client.patch(
            f"/v1/documents/{doc_id}",
            json={"folder_id": fake_folder_id},
            headers={"X-API-Key": api_key},
        )
        assert update_response.status_code == 404

    async def test_delete_folder_with_contents(self, client, api_key, db_session, test_tenant_id):
        """Deleting a folder with delete_contents=True should delete documents."""
        # Seed a document
        doc_id = f"doc_{uuid.uuid4().hex[:16]}"
        doc = Document(
            id=doc_id,
            tenant_id=test_tenant_id,
            filename="test_recursive.txt",
            status=DocumentStatus.READY,
            content_hash=uuid.uuid4().hex,
            storage_path="test/path/recursive.txt",
        )
        db_session.add(doc)
        await db_session.commit()
        # Create folder
        folder_name = f"recursive-delete-{uuid.uuid4().hex[:8]}"
        folder_response = await client.post(
            "/v1/folders",
            json={"name": folder_name},
            headers={"X-API-Key": api_key},
        )
        assert folder_response.status_code == 201
        folder_id = folder_response.json()["id"]

        # Get a document (assuming one exists or we might need to skip if empty env)
        docs_response = await client.get(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        documents = docs_response.json()
        if not documents:
            pytest.fail("Document seeding failed")

        # Use the first document
        doc_id = documents[0]["id"]

        # Assign to folder
        await client.patch(
            f"/v1/documents/{doc_id}",
            json={"folder_id": folder_id},
            headers={"X-API-Key": api_key},
        )

        # Delete folder with delete_contents=True
        delete_response = await client.delete(
            f"/v1/folders/{folder_id}",
            params={"delete_contents": True},
            headers={"X-API-Key": api_key},
        )
        assert delete_response.status_code == 204

        # Verify document is actually deleted (should return 404)
        doc_response = await client.get(
            f"/v1/documents/{doc_id}",
            headers={"X-API-Key": api_key},
        )
        assert doc_response.status_code == 404
