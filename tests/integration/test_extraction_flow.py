"""
Extraction Integration Test
===========================

Verifies the extraction pipeline components (Registry, Extractors).
"""

import pytest
import os
from src.core.extraction.registry import ExtractorRegistry
from src.core.extraction.local.pymupdf_extractor import PyMuPDFExtractor
from src.core.extraction.local.unstructured_extractor import UnstructuredExtractor

# Mock data
SAMPLE_PDF_CONTENT = b"%PDF-1.4..." # Not a real PDF, would fail actual extraction but good for registry test if we mock method
SAMPLE_TEXT_CONTENT = b"Hello world"

@pytest.mark.asyncio
async def test_extractor_registry():
    # 1. Test PDF routing
    extractor = ExtractorRegistry.get_extractor("application/pdf")
    assert isinstance(extractor, PyMuPDFExtractor)
    assert extractor.name == "pymupdf4llm"
    
    # 2. Test Text/Docx routing (fallback)
    extractor = ExtractorRegistry.get_extractor("text/plain")
    assert isinstance(extractor, UnstructuredExtractor)
    assert extractor.name == "unstructured"
    
    # 3. Test Unknown type error behavior
    # Actually our registry falls back to unstructured if enabled, 
    # so we might not raise error easily unless disabled.
    # Let's verify unstructured is default fallback.
    extractor = ExtractorRegistry.get_extractor("application/octet-stream")
    assert isinstance(extractor, UnstructuredExtractor)

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
