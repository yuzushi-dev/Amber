"""
Extraction Integration Test
===========================

Verifies the extraction pipeline components (Registry, Extractors).
"""


import pytest

from src.core.extraction.local.unstructured_extractor import UnstructuredExtractor
from src.core.extraction.registry import ExtractorRegistry

# Mock data
SAMPLE_PDF_CONTENT = b"%PDF-1.4..." # Not a real PDF, would fail actual extraction but good for registry test if we mock method
SAMPLE_TEXT_CONTENT = b"Hello world"

@pytest.mark.asyncio
async def test_extractor_registry():
    """Test that the registry returns appropriate extractors for different file types."""
    from src.core.extraction.base import BaseExtractor

    # 1. Test PDF routing - should return some extractor
    extractor = ExtractorRegistry.get_extractor("application/pdf")
    assert isinstance(extractor, BaseExtractor)
    # Could be PyMuPDF if enabled, or Unstructured as fallback
    assert extractor.name in ("pymupdf4llm", "pymupdf", "unstructured")

    # 2. Test Text/plain routing
    extractor = ExtractorRegistry.get_extractor("text/plain")
    assert isinstance(extractor, BaseExtractor)
    # Should be PlainTextExtractor or Unstructured
    assert extractor.name in ("plaintext", "unstructured")

    # 3. Test Unknown type fallback behavior
    # Should fall back to unstructured if enabled
    extractor = ExtractorRegistry.get_extractor("application/octet-stream")
    assert isinstance(extractor, BaseExtractor)

@pytest.mark.asyncio
async def test_unstructured_extractor_basic():
    # Test simple text extraction with unstructured
    extractor = UnstructuredExtractor()
    result = await extractor.extract(
        file_content=b"This is a test document.",
        file_type="text/plain"
    )

    assert result.content.strip() == "This is a test document."
    assert result.extractor_used == "unstructured"
    assert result.confidence > 0.0

# Note: Testing PyMuPDF requires a real valid PDF bytes sequence or it raises error.
# We will skip deep functional test of PyMuPDF in this lightweight integration test
# unless we have a fixture PDF.
