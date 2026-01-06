"""
Unit Tests for Stale Document Recovery
=======================================

Tests the recovery module that handles documents stuck in processing states.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.state.machine import DocumentStatus


class TestStaleDocumentRecovery:
    """Tests for the recover_stale_documents function."""

    @pytest.fixture
    def mock_document_extracting(self):
        """Create a mock document in EXTRACTING state."""
        doc = MagicMock()
        doc.id = "doc_123"
        doc.filename = "test.pdf"
        doc.status = DocumentStatus.EXTRACTING.value
        doc.updated_at = datetime.now(UTC)
        return doc

    @pytest.fixture
    def mock_document_chunking_with_chunks(self):
        """Create a mock document in CHUNKING state with existing chunks."""
        doc = MagicMock()
        doc.id = "doc_456"
        doc.filename = "with_chunks.pdf"
        doc.status = DocumentStatus.CHUNKING.value
        doc.updated_at = datetime.now(UTC)
        return doc

    @pytest.mark.asyncio
    async def test_no_stale_documents(self):
        """Test when no documents are in stale states."""
        from src.workers.recovery import recover_stale_documents

        with patch("src.workers.recovery.create_async_engine") as mock_engine, \
             patch("src.workers.recovery.sessionmaker") as mock_sessionmaker:

            # Setup mocks
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_sessionmaker.return_value.return_value = mock_session
            mock_engine.return_value.dispose = AsyncMock()

            result = await recover_stale_documents()

            assert result["recovered"] == 0
            assert result["failed"] == 0
            assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_document_in_extracting_marked_failed(self, mock_document_extracting):
        """Test that document in EXTRACTING state is marked as FAILED."""
        from src.workers.recovery import recover_stale_documents

        with patch("src.workers.recovery.create_async_engine") as mock_engine, \
             patch("src.workers.recovery.sessionmaker") as mock_sessionmaker, \
             patch("src.workers.recovery._publish_recovery_status"):

            # Setup mocks
            mock_session = AsyncMock()

            # First query returns stale documents
            mock_result_stale = MagicMock()
            mock_result_stale.scalars.return_value.all.return_value = [mock_document_extracting]

            # Second query (chunks) returns no chunks
            mock_result_chunks = MagicMock()
            mock_result_chunks.scalars.return_value.first.return_value = None

            mock_session.execute = AsyncMock(side_effect=[mock_result_stale, mock_result_chunks])
            mock_session.commit = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_sessionmaker.return_value.return_value = mock_session
            mock_engine.return_value.dispose = AsyncMock()

            result = await recover_stale_documents()

            # Document should be marked as failed
            assert result["failed"] == 1
            assert result["total"] == 1
            assert mock_document_extracting.status == DocumentStatus.FAILED

    @pytest.mark.asyncio
    async def test_document_chunking_with_chunks_recovered(self, mock_document_chunking_with_chunks):
        """Test that document in CHUNKING state with chunks is recovered to READY."""
        from src.workers.recovery import recover_stale_documents

        with patch("src.workers.recovery.create_async_engine") as mock_engine, \
             patch("src.workers.recovery.sessionmaker") as mock_sessionmaker, \
             patch("src.workers.recovery._publish_recovery_status"):

            mock_session = AsyncMock()

            # First query returns stale documents
            mock_result_stale = MagicMock()
            mock_result_stale.scalars.return_value.all.return_value = [mock_document_chunking_with_chunks]

            # Second query (chunks) returns a chunk
            mock_chunk = MagicMock()
            mock_result_chunks = MagicMock()
            mock_result_chunks.scalars.return_value.first.return_value = mock_chunk

            mock_session.execute = AsyncMock(side_effect=[mock_result_stale, mock_result_chunks])
            mock_session.commit = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_sessionmaker.return_value.return_value = mock_session
            mock_engine.return_value.dispose = AsyncMock()

            result = await recover_stale_documents()

            # Document should be recovered to READY
            assert result["recovered"] == 1
            assert result["total"] == 1
            assert mock_document_chunking_with_chunks.status == DocumentStatus.READY


class TestSyncRecoveryWrapper:
    """Tests for the synchronous wrapper function."""

    def test_run_recovery_sync_runs_async(self):
        """Test that run_recovery_sync properly wraps async function."""
        from src.workers.recovery import run_recovery_sync

        with patch("src.workers.recovery.recover_stale_documents") as mock_recover:
            mock_recover.return_value = {"recovered": 0, "failed": 0, "total": 0}

            result = run_recovery_sync()

            assert result == {"recovered": 0, "failed": 0, "total": 0}
