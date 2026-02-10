import io
import json
import zipfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.core.admin_ops.application.backup_service import BackupService
from src.core.admin_ops.application.restore_service import RestoreService
from src.core.admin_ops.domain.backup_job import BackupSchedule, BackupScope, RestoreMode
from src.core.admin_ops.domain.global_rule import GlobalRule
from src.core.generation.domain.memory_models import ConversationSummary, UserFact
from src.core.ingestion.domain.chunk import EmbeddingStatus
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant


async def mock_aiter(items):
    for item in items:
        yield item


# --- Mocks ---


@pytest_asyncio.fixture
async def mock_session():
    session = AsyncMock()
    # Mock execute result
    msg_mock = MagicMock()
    msg_mock.scalars.return_value.all.return_value = []
    msg_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = msg_mock
    return session


@pytest_asyncio.fixture
async def mock_storage():
    storage = MagicMock()
    storage.upload_file = MagicMock()
    storage.get_file = MagicMock()
    storage.delete_file = MagicMock()
    return storage


@pytest_asyncio.fixture
async def backup_service(mock_session, mock_storage):
    return BackupService(mock_session, mock_storage)


@pytest_asyncio.fixture
async def restore_service(mock_session, mock_storage):
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
        created_at=datetime.now(UTC),
    )

    # 2. Folders
    folder = Folder(
        id="folder_1", tenant_id="tenant_1", name="Documents", created_at=datetime.now(UTC)
    )

    # 3. Conversations
    conv = ConversationSummary(
        id="conv_1",
        tenant_id="tenant_1",
        user_id="user_1",
        title="Test Chat",
        summary="Summary",
        created_at=datetime.now(UTC),
    )

    # 4. User Facts
    fact = UserFact(
        id="fact_1",
        tenant_id="tenant_1",
        user_id="user_1",
        content="User likes AI",
        importance=5,
        created_at=datetime.now(UTC),
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

    result_mock_chunks = MagicMock()
    result_mock_chunks.scalars.return_value.all.return_value = []

    # BackupService:
    # 1. _add_documents_metadata -> select(Document)
    # 2. _add_folders -> select(Folder)
    # 3. _add_document_files -> select(Document)
    # 4. _add_conversations -> select(ConversationSummary)
    # 5. _add_user_facts -> select(UserFact)
    # 6. _add_conversation_summaries (pass)

    mock_session.execute.side_effect = [
        result_mock_docs,  # Metadata
        result_mock_folders,  # Folders
        result_mock_docs,  # Files
        result_mock_conv,  # Conversations
        result_mock_facts,  # Facts
        result_mock_chunks,  # Chunks
    ]

    # Mock storage file retrieval
    mock_storage.get_file.return_value = b"fake-pdf-content"

    # Patch platform for Vectors/Graph
    with patch("src.amber_platform.composition_root.platform") as mock_platform:
        # Mock iterators using side_effect to return fresh generators
        mock_platform.milvus_vector_store.export_vectors.side_effect = lambda *a, **k: mock_aiter(
            [{"id": "v1"}]
        )
        mock_platform.neo4j_client.export_graph.side_effect = lambda *a, **k: mock_aiter(
            [{"id": "g1"}]
        )

        # Execute
        path, size = await backup_service.create_backup(
            tenant_id="tenant_1", job_id="job_1", scope=BackupScope.USER_DATA
        )

    # Asserts
    assert path == "backups/tenant_1/job_1/backup.zip"
    assert size > 0
    mock_storage.upload_file.assert_called_once()

    # Verify ZIP content (inspect the arguments passed to mock_storage.upload_file)
    call_args = mock_storage.upload_file.call_args
    uploaded_data = call_args.kwargs["data"]

    with zipfile.ZipFile(uploaded_data, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "documents/metadata.json" in namelist
        assert "folders/folders.json" in namelist
        assert "conversations/conversations.json" in namelist
        assert "memory/user_facts.json" in namelist
        assert (
            "documents/files/root/test.pdf" in namelist
        )  # Should use 'root' as folder_id is None in mock if not set

        # Verify metadata content
        meta_json = json.loads(zf.read("documents/metadata.json"))
        assert len(meta_json) == 1
        assert meta_json[0]["id"] == "doc_1"
        assert meta_json[0]["mime_type"] == "application/pdf"  # This verifies our fix


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
            "job_id": "job_1",
        }
        zf.writestr("manifest.json", json.dumps(manifest))

        # Documents
        docs_meta = [
            {
                "id": "doc_1",
                "filename": "restored.pdf",
                "folder_id": None,
                "storage_path": "path/old.pdf",
                "mime_type": "application/pdf",
                "file_size": 123,
                "status": "completed",
                "metadata": {},
                "index": 0,
                "tokens": 100,
                "embedding_status": EmbeddingStatus.COMPLETED.value,
            }
        ]
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
        id="doc_1", storage_path="path/old.pdf", metadata_={"mime_type": "application/pdf"}
    )

    # helper to create a mock result
    def create_mock_result(return_value):
        m = MagicMock()
        m.scalar_one_or_none.return_value = return_value
        return m

    mock_session.execute.side_effect = [
        create_mock_result(None),  # Doc check (metadata restore)
        create_mock_result(restored_doc),  # Doc lookup (file restore)
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
    assert call_args.kwargs["content_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_restore_full_system_config(restore_service, mock_session, mock_storage):
    """Test restoring configuration files (System Config)."""
    # Prepare ZIP with config files
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps({"version": "1.0", "tenant_id": "t1", "scope": "full_system"}),
        )

        # Tenant Config
        zf.writestr(
            "config/tenant_config.json",
            json.dumps({"id": "t1", "config": {"theme": "dark"}, "name": "New Name"}),
        )

        # Global Rules
        zf.writestr(
            "config/global_rules.json",
            json.dumps([{"id": "rule_1", "content": "Rule 1", "category": "safety"}]),
        )

        # Backup Schedules
        zf.writestr(
            "config/backup_schedules.json",
            json.dumps(
                [{"id": "sched_1", "frequency": "daily", "time_utc": "02:00", "enabled": "true"}]
            ),
        )

    zip_buffer.seek(0)
    mock_storage.get_file.return_value = zip_buffer.getvalue()

    # Mock mocks
    mock_session.add = MagicMock()

    # For tenant update, we need to return an existing tenant
    tenant_mock = Tenant(id="t1", name="Old Name", config={})

    # Session execute side effects
    # 1. Clear Tenant Data (4 deletes)
    # 2. Check Folders (if any, skipping empty check) -> 0 folders in zip
    # 3. Check Docs -> 0 docs
    # 4. Check Convs -> 0 convs
    # 5. Check Facts -> 0 facts
    # 6. Delete Global Rules (Replace mode) -> 1 delete
    # 7. Restore Rules -> Add
    # 8. Delete Schedules (Replace mode) -> 1 delete
    # 9. Restore Schedules -> Add
    # 10. Restore Tenant Config -> Select Tenant

    # We only care about step 10 returning a tenant
    def side_effect_handler(*args, **kwargs):
        stmt = args[0]
        # Very simple heuristic matching for mock
        s_str = str(stmt)
        m = MagicMock()

        if "FROM tenants" in s_str.upper() or "tenants.id" in s_str.lower():
            m.scalar_one_or_none.return_value = tenant_mock
            return m

        m.scalar_one_or_none.return_value = None
        m.scalars.return_value.all.return_value = []
        return m

    mock_session.execute.side_effect = side_effect_handler

    # Execute
    await restore_service.restore(
        target_tenant_id="t1", backup_path="backup_sys", mode=RestoreMode.REPLACE
    )

    # Verify Tenant Update
    assert tenant_mock.config == {"theme": "dark"}
    assert tenant_mock.name == "New Name"
    # assert mock_session.add.called_with(tenant_mock) # Check if add was called

    # Verify Insertions
    # We expect rule and schedule to be added
    added_objs = [call[0][0] for call in mock_session.add.call_args_list]

    has_rule = any(isinstance(o, GlobalRule) and o.id == "rule_1" for o in added_objs)
    has_sched = any(
        isinstance(o, BackupSchedule) and o.id == "sched_1" and o.frequency == "daily"
        for o in added_objs
    )

    assert has_rule
    assert has_sched


@pytest.mark.asyncio
async def test_restore_extended_components(restore_service, mock_session, mock_storage, caplog):
    """Test chunks, vectors, graph, and dump restore."""
    # ZIP content
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps({"version": "1.0", "tenant_id": "t1", "scope": "full_system"}),
        )

        # Chunks
        zf.writestr(
            "ingestion/chunks.json",
            json.dumps(
                [
                    {
                        "id": "chunk_1",
                        "document_id": "doc_1",
                        "content": "text",
                        "index": 0,
                        "tokens": 10,
                    }
                ]
            ),
        )

        # Vectors
        zf.writestr("vectors/vectors.jsonl", json.dumps({"id": "v1", "vector": [0.1]}) + "\n")

        # Graph
        zf.writestr("graph/graph.jsonl", json.dumps({"type": "node", "id": "n1"}) + "\n")

    zip_buffer.seek(0)
    mock_storage.get_file.return_value = zip_buffer.getvalue()

    # Mock Chunks check
    mock_session.execute.return_value.scalar_one_or_none.return_value = None  # No existing chunk
    mock_session.add = MagicMock()  # Ensure sync mock for add

    # Mock Platform
    with patch("src.amber_platform.composition_root.platform") as mock_platform:
        mock_platform.milvus_vector_store.import_vectors = AsyncMock(return_value=10)
        mock_platform.neo4j_client.import_graph = AsyncMock(return_value={"nodes_created": 1})

        await restore_service.restore("backup_ext", "t1", RestoreMode.MERGE)

        # Verify Chunks
        # Check logs if failed
        errors = [r.message for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
        assert mock_session.add.call_count >= 1, f"Session add not called. Errors: {errors}"

        # Verify Vectors
        mock_platform.milvus_vector_store.import_vectors.assert_called_once()

        # Verify Graph
        mock_platform.neo4j_client.import_graph.assert_called_once()


@pytest.mark.asyncio
async def test_restore_postgres_dump(restore_service, mock_session, mock_storage):
    """Test full system dump restore triggers psql."""
    # ZIP with dump
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps({"version": "1.0", "tenant_id": "t1", "scope": "full_system"}),
        )
        zf.writestr("database/postgres_dump.sql", b"SQL DUMP CONTENT")

    zip_buffer.seek(0)
    mock_storage.get_file.return_value = zip_buffer.getvalue()

    # Patch subprocess
    with patch("src.core.admin_ops.application.restore_service.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        # Patch settings
        with patch("src.api.config.settings") as mock_settings:
            mock_settings.db.database_url = "postgresql://u:p@h:5432/db"

            await restore_service.restore("backup_dump", "t1", RestoreMode.REPLACE)

            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "psql"
            assert "-f" in args
