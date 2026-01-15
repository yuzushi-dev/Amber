"""
Unit tests for ExportService.
Tests ZIP generation, conversation formatting, and error handling with mocked dependencies.
"""

import io
import json
import zipfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models.export_job import ExportJob, ExportStatus
from src.core.models.memory import ConversationSummary
# Import all models to ensure SQLAlchemy relationships resolve properly
from src.core.models.document import Document
from src.core.models.folder import Folder
from src.core.models.chunk import Chunk


class TestExportService:
    """Tests for the ExportService class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async session."""
        session = AsyncMock()
        return session

    @pytest.fixture
    def mock_storage(self):
        """Create a mock MinIO storage client."""
        storage = MagicMock()
        storage.get_file = MagicMock(return_value=b"fake document content")
        storage.upload_file = MagicMock()
        return storage

    @pytest.fixture
    def sample_conversation(self):
        """Create a sample conversation summary."""
        conv = MagicMock(spec=ConversationSummary)
        conv.id = "conv_123"
        conv.tenant_id = "tenant_1"
        conv.user_id = "user_1"
        conv.title = "Test Conversation"
        conv.summary = "This is a test summary"
        conv.created_at = datetime(2026, 1, 14, 12, 0, 0)
        conv.metadata_ = {
            "query": "What is Python?",
            "answer": "Python is a programming language.",
            "history": [
                {
                    "query": "What is Python?",
                    "answer": "Python is a programming language.",
                    "sources": [
                        {
                            "document_id": "doc_1",
                            "filename": "python_guide.pdf",
                            "content": "Python is versatile...",
                            "score": 0.95
                        }
                    ]
                }
            ]
        }
        return conv

    @pytest.mark.asyncio
    async def test_generate_single_conversation_zip_basic(self, mock_session, mock_storage, sample_conversation):
        """Test generating a ZIP for a single conversation."""
        # Mock the database query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_conversation
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.core.services.export_service.MinIOClient", return_value=mock_storage):
            from src.core.services.export_service import ExportService

            service = ExportService(mock_session, mock_storage)
            
            zip_bytes = await service.generate_single_conversation_zip("conv_123")

        # Verify ZIP is valid and has expected files
        assert len(zip_bytes) > 0
        
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            file_list = zf.namelist()
            
            assert "transcript.txt" in file_list
            assert "metadata.json" in file_list
            
            # Check transcript content
            transcript = zf.read("transcript.txt").decode("utf-8")
            assert "What is Python?" in transcript
            assert "Python is a programming language." in transcript
            
            # Check metadata content
            metadata = json.loads(zf.read("metadata.json").decode("utf-8"))
            assert metadata["conversation_id"] == "conv_123"
            assert metadata["tenant_id"] == "tenant_1"
            assert len(metadata["chunks"]) > 0

    @pytest.mark.asyncio
    async def test_generate_single_conversation_zip_not_found(self, mock_session, mock_storage):
        """Test error when conversation is not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        from src.core.services.export_service import ExportService

        service = ExportService(mock_session, mock_storage)

        with pytest.raises(ValueError, match="Conversation .* not found"):
            await service.generate_single_conversation_zip("nonexistent_conv")

    @pytest.mark.asyncio
    async def test_generate_single_conversation_zip_with_documents(self, mock_session, mock_storage, sample_conversation):
        """Test that referenced documents are included in the ZIP."""
        # Mock conversation query
        mock_conv_result = MagicMock()
        mock_conv_result.scalar_one_or_none.return_value = sample_conversation
        
        # Mock document query
        mock_doc = MagicMock()
        mock_doc.id = "doc_1"
        mock_doc.filename = "python_guide.pdf"
        mock_doc.storage_path = "uploads/doc_1.pdf"
        
        mock_doc_result = MagicMock()
        mock_doc_result.scalar_one_or_none.return_value = mock_doc
        
        # Return conversation first, then document
        mock_session.execute = AsyncMock(side_effect=[mock_conv_result, mock_doc_result])

        from src.core.services.export_service import ExportService

        service = ExportService(mock_session, mock_storage)
        
        zip_bytes = await service.generate_single_conversation_zip("conv_123")

        # Verify document folder exists
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            file_list = zf.namelist()
            # Check that documents folder has content
            doc_files = [f for f in file_list if f.startswith("documents/")]
            assert len(doc_files) > 0

    @pytest.mark.asyncio
    async def test_generate_single_conversation_zip_handles_missing_document(self, mock_session, mock_storage, sample_conversation):
        """Test graceful handling when document file is not in storage."""
        mock_conv_result = MagicMock()
        mock_conv_result.scalar_one_or_none.return_value = sample_conversation
        
        # Mock document exists in DB but not in storage
        mock_doc = MagicMock()
        mock_doc.id = "doc_1"
        mock_doc.filename = "missing_doc.pdf"
        mock_doc.storage_path = "uploads/missing.pdf"
        
        mock_doc_result = MagicMock()
        mock_doc_result.scalar_one_or_none.return_value = mock_doc
        
        mock_session.execute = AsyncMock(side_effect=[mock_conv_result, mock_doc_result])
        
        # Storage raises FileNotFoundError
        mock_storage.get_file = MagicMock(side_effect=FileNotFoundError("File not found"))

        from src.core.services.export_service import ExportService

        service = ExportService(mock_session, mock_storage)
        
        # Should not raise - just logs warning and adds placeholder
        zip_bytes = await service.generate_single_conversation_zip("conv_123")
        
        assert len(zip_bytes) > 0
        
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            # Check for .missing.txt placeholder
            file_list = zf.namelist()
            missing_files = [f for f in file_list if ".missing.txt" in f]
            assert len(missing_files) > 0

    @pytest.mark.asyncio
    async def test_generate_single_conversation_zip_fallback_format(self, mock_session, mock_storage):
        """Test fallback format when no history array exists."""
        conv = MagicMock(spec=ConversationSummary)
        conv.id = "conv_456"
        conv.tenant_id = "tenant_1"
        conv.user_id = "user_1"
        conv.title = "Simple Query"
        conv.summary = "Simple answer"
        conv.created_at = datetime(2026, 1, 14, 12, 0, 0)
        conv.metadata_ = {
            "query": "Hello?",
            "answer": "Hi there!"
        }  # No "history" array

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = conv
        mock_session.execute = AsyncMock(return_value=mock_result)

        from src.core.services.export_service import ExportService

        service = ExportService(mock_session, mock_storage)
        
        zip_bytes = await service.generate_single_conversation_zip("conv_456")

        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            transcript = zf.read("transcript.txt").decode("utf-8")
            assert "Hello?" in transcript
            assert "Hi there!" in transcript


class TestExportJobModel:
    """Tests for the ExportJob model."""

    def test_export_job_creation(self):
        """Test ExportJob model can be instantiated."""
        job = ExportJob(
            id="job_123",
            tenant_id="tenant_1",
            status=ExportStatus.PENDING
        )

        assert job.id == "job_123"
        assert job.tenant_id == "tenant_1"
        assert job.status == ExportStatus.PENDING
        assert job.result_path is None
        assert job.error_message is None

    def test_export_job_repr(self):
        """Test ExportJob string representation."""
        job = ExportJob(
            id="job_456",
            tenant_id="tenant_1",
            status=ExportStatus.COMPLETED
        )

        repr_str = repr(job)
        assert "job_456" in repr_str
        assert "tenant_1" in repr_str

    def test_export_status_enum_values(self):
        """Test ExportStatus enum has expected values."""
        assert ExportStatus.PENDING.value == "pending"
        assert ExportStatus.RUNNING.value == "running"
        assert ExportStatus.COMPLETED.value == "completed"
        assert ExportStatus.FAILED.value == "failed"
