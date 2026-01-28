
import pytest
import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.core.admin_ops.application.backup_service import BackupService
from src.core.admin_ops.application.restore_service import RestoreService
from src.core.admin_ops.domain.backup_job import BackupScope, RestoreMode
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.ingestion.domain.chunk import Chunk
from src.core.generation.domain.memory_models import ConversationSummary, UserFact
from src.core.state.machine import DocumentStatus

# --- Mocks ---

@pytest.fixture
def mock_session():
    session = AsyncMock()
    # Mock execute result
    msg_mock = MagicMock()
    msg_mock.scalars.return_value.all.return_value = []
    msg_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = msg_mock
    return session

@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.upload_file = MagicMock()
    storage.get_file = MagicMock()
    storage.delete_file = MagicMock()
    return storage

@pytest.fixture
def backup_service(mock_session, mock_storage):
    return BackupService(mock_session, mock_storage)

@pytest.fixture
def restore_service(mock_session, mock_storage):
    return RestoreService(mock_session, mock_storage)

# --- Tests for BackupService ---

@pytest.mark.asyncio
async def test_create_backup_user_data(backup_service, mock_session, mock_storage):
    # Setup mock data using proper SQLAlchemy models
    
    # 1. Documents
    doc = Document(
        id="doc_1", 
        tenant_id="tenant_1", 
        filename="test.pdf", 
        content_hash="hash",
        storage_path="path/to/doc.pdf",
        status=DocumentStatus.INGESTED,
        metadata_={"mime_type": "application/pdf", "file_size": 1024},
        created_at=datetime.utcnow()
    )
    
    # 2. Folders
    folder = Folder(
        id="folder_1",
        tenant_id="tenant_1",
        name="Documents",
        created_at=datetime.utcnow()
    )
    
    # 3. Conversations
    conv = ConversationSummary(
        id="conv_1",
        tenant_id="tenant_1",
        user_id="user_1",
        title="Test Chat",
        summary="Summary",
        created_at=datetime.utcnow()
    )
    
    # 4. User Facts
    fact = UserFact(
        id="fact_1",
        tenant_id="tenant_1",
        user_id="user_1",
        content="User likes AI",
        importance=5,
        created_at=datetime.utcnow()
    )

    # Configure session execute side effects to return data in order of calls
    # Order in BackupService.create_backup:
    # 1. Documents (metadata)
    # 2. Folders
    # 3. Documents (files)
    # 4. Conversations
    # 5. User Facts
    # 6. Conversation Summaries (not implemented yet/reuses logic)
    
    result_mock_docs = MagicMock()
    result_mock_docs.scalars.return_value.all.return_value = [doc]
    
    result_mock_folders = MagicMock()
    result_mock_folders.scalars.return_value.all.return_value = [folder]
    
    result_mock_conv = MagicMock()
    result_mock_conv.scalars.return_value.all.return_value = [conv]
    
    result_mock_facts = MagicMock()
    result_mock_facts.scalars.return_value.all.return_value = [fact]

    # BackupService:
    # 1. _add_documents_metadata -> select(Document)
    # 2. _add_folders -> select(Folder)
    # 3. _add_document_files -> select(Document)
    # 4. _add_conversations -> select(ConversationSummary)
    # 5. _add_user_facts -> select(UserFact)
    # 6. _add_conversation_summaries (pass)
    
    mock_session.execute.side_effect = [
        result_mock_docs,    # Metadata
        result_mock_folders, # Folders
        result_mock_docs,    # Files
        result_mock_conv,    # Conversations
        result_mock_facts,   # Facts
    ]
    
    # Mock storage file retrieval
    mock_storage.get_file.return_value = b"fake-pdf-content"

    # Execute
    path, size = await backup_service.create_backup(
        tenant_id="tenant_1",
        job_id="job_1",
        scope=BackupScope.USER_DATA
    )

    # Asserts
    assert path == "backups/tenant_1/job_1/backup.zip"
    assert size > 0
    mock_storage.upload_file.assert_called_once()
    
    # Verify ZIP content (inspect the arguments passed to mock_storage.upload_file)
    call_args = mock_storage.upload_file.call_args
    uploaded_data = call_args.kwargs['data']
    
    with zipfile.ZipFile(uploaded_data, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "documents/metadata.json" in namelist
        assert "folders/folders.json" in namelist
        assert "conversations/conversations.json" in namelist
        assert "memory/user_facts.json" in namelist
        assert "documents/files/root/test.pdf" in namelist # Should use 'root' as folder_id is None in mock if not set
        
        # Verify metadata content
        meta_json = json.loads(zf.read("documents/metadata.json"))
        assert len(meta_json) == 1
        assert meta_json[0]["id"] == "doc_1"
        assert meta_json[0]["mime_type"] == "application/pdf" # This verifies our fix


@pytest.mark.asyncio
async def test_restore_backup(restore_service, mock_session, mock_storage):
    # Prepare a fake backup zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Manifest
        manifest = {
            "version": "1.0",
            "created_at": "2023-01-01T00:00:00",
            "tenant_id": "tenant_1",
            "scope": "user_data",
            "job_id": "job_1"
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        
        # Documents
        docs_meta = [{
            "id": "doc_1",
            "filename": "restored.pdf",
            "folder_id": None,
            "storage_path": "path/old.pdf",
            "mime_type": "application/pdf",
            "file_size": 123,
            "status": "completed",
            "metadata": {},
            "created_at": None,
            "updated_at": None
        }]
        zf.writestr("documents/metadata.json", json.dumps(docs_meta))
        
        # File content
        zf.writestr("documents/files/root/restored.pdf", b"restored content")

    zip_buffer.seek(0)
    mock_storage.get_file.return_value = zip_buffer.getvalue()
    
    # Mock session.add as synchronous MagicMock
    mock_session.add = MagicMock()
    
    # Mock exists check for documents (return None means doesn't exist)
    # Then for file restoration, it needs to find the document we just "added"
    
    # Mock scalar_one_or_none behavior
    # We need a bit more sophisticated mock here because we have multiple execute calls
    # 1. Check folder exists (Merge mode) -> None
    # 2. Check doc exists (Merge mode) -> None
    # 3. Check conversation exists -> None
    # 4. Check fact exists -> None
    # 5. Look up document for file restore -> Document object
    
    # Create the document that "exists" for step 5
    restored_doc = Document(
        id="doc_1", 
        storage_path="path/old.pdf",
        metadata_={"mime_type": "application/pdf"}
    )
    
    # helper to create a mock result
    def create_mock_result(return_value):
        m = MagicMock()
        m.scalar_one_or_none.return_value = return_value
        return m

    mock_session.execute.side_effect = [
        create_mock_result(None), # Doc check (metadata restore)
        create_mock_result(restored_doc), # Doc lookup (file restore)
    ]

    # Execute
    await restore_service.restore(
        target_tenant_id="tenant_1",
        backup_path="backup_1",
        mode=RestoreMode.MERGE,
    )

    # Verify document insertion
    assert mock_session.add.call_count >= 1
    
    # Verify file upload (restoring file content)
    assert mock_storage.upload_file.call_count >= 1
    call_args = mock_storage.upload_file.call_args
    assert call_args.kwargs['content_type'] == "application/pdf"
    
