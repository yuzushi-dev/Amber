"""
Domain Classification Integration Test
======================================

Verifies the domain classifier and ingestion integration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.intelligence.classifier import DomainClassifier
from src.core.intelligence.strategies import DocumentDomain, get_strategy
from src.core.models.chunk import Chunk
from src.core.models.document import Document
from src.core.services.ingestion import IngestionService
from src.core.state.machine import DocumentStatus


@pytest.mark.asyncio
async def test_domain_classifier_logic():
    """Test the heuristic logic (mock LLM behavior)."""
    classifier = DomainClassifier()

    # Test Technical
    domain = await classifier.classify("def my_function(): return True")
    assert domain == DocumentDomain.TECHNICAL

    # Test Legal
    domain = await classifier.classify("This agreement is entered into by and between...")
    assert domain == DocumentDomain.LEGAL

    # Test General
    domain = await classifier.classify("Once upon a time in a generic text...")
    assert domain == DocumentDomain.GENERAL

    await classifier.close()

@pytest.mark.asyncio
async def test_strategy_mapping():
    """Test that domains map to correct strategies."""
    strategy = get_strategy("legal")
    assert strategy.chunk_size == 1000
    assert strategy.chunk_overlap == 100

    strategy = get_strategy("technical")
    assert strategy.chunk_size == 800

@pytest.mark.asyncio
async def test_ingestion_integration_classification(db_session):
    """
    Verify IngestionService.process_document invokes classification.
    We mock the storage and classifier to focus on the flow.
    """
    # Setup mocks
    mock_storage = MagicMock()
    mock_response = MagicMock()
    mock_response.read.return_value = b"def code(): pass" # Technical content
    mock_storage.get_file.return_value = mock_response

    # Create service
    service = IngestionService(db_session, mock_storage)

    import uuid
    # Pre-seed document in DB
    doc_id = str(uuid.uuid4())
    doc = Document(id=doc_id, tenant_id="t1", filename="code.py", status=DocumentStatus.INGESTED, content_hash=str(uuid.uuid4()), storage_path="path")
    db_session.add(doc)
    await db_session.commit()

    # Patch dependencies
    # We patch FallbackManager to return content directly
    # We patch DomainClassifier to use the real one (or mock if we wanted strict unit)
    # Since our real one has heuristics, we can use it.

    mock_extraction_result = MagicMock()
    mock_extraction_result.content = "def code(): pass"
    mock_extraction_result.extractor_used = "test"
    mock_extraction_result.confidence = 1.0
    mock_extraction_result.metadata = {}
    mock_extraction_result.extraction_time_ms = 10

    with patch("src.core.extraction.fallback.FallbackManager.extract_with_fallback", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = mock_extraction_result

        # Run process
        await service.process_document(doc_id)

    # Verify DB state
    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.READY
    assert doc.domain == DocumentDomain.TECHNICAL

    # Verify Chunk metadata
    # We need to query chunks
    from sqlalchemy import select
    result = await db_session.execute(select(Chunk).where(Chunk.document_id == doc_id))
    chunk = result.scalars().first()

    assert chunk is not None
    assert chunk.metadata_["domain"] == "technical"
    assert chunk.metadata_["strategy"]["name"] == "technical"
    assert chunk.metadata_["strategy"]["chunk_size"] == 800
