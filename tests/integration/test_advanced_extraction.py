"""
Advanced Extraction Integration Test
====================================

Verifies the fallback manager logic.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.core.extraction.base import ExtractionResult
from src.core.extraction.config import extraction_settings
from src.core.extraction.fallback import FallbackManager

# Since we don't assume external tools (Marker, Mistral) are usable in test env,
# we will mock the extractors to verify the CHAIN logic.

@pytest.mark.asyncio
async def test_fallback_chain_primary_success():
    """Test that if primary succeeds, chain stops."""
    content = b"Simple content"

    # Mock primary extractor (Registry lookup)
    mock_primary = AsyncMock()
    mock_primary.name = "primary"
    mock_primary.extract.return_value = ExtractionResult(content="Primary Success", extractor_used="primary")

    with patch("src.core.extraction.registry.ExtractorRegistry.get_extractor", return_value=mock_primary):
        result = await FallbackManager.extract_with_fallback(content, "application/pdf", "test.pdf")

    assert result.content == "Primary Success"
    assert result.extractor_used == "primary"
    mock_primary.extract.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_chain_secondary_marker():
    """Test fallback to Marker if primary fails."""
    content = b"Complex content"

    # Enable Marker
    extraction_settings.marker_enabled = True

    # Mock primary to fail
    mock_primary = AsyncMock()
    mock_primary.name = "primary"
    mock_primary.extract.side_effect = RuntimeError("Primary Failed")

    # Mock Marker
    # We patch the class constructor to return our mock instance
    with patch("src.core.extraction.registry.ExtractorRegistry.get_extractor", return_value=mock_primary), \
         patch("src.core.extraction.fallback.MarkerExtractor") as MockMarker:

        mock_marker_instance = AsyncMock()
        mock_marker_instance.name = "marker"
        mock_marker_instance.extract.return_value = ExtractionResult(content="Marker Success", extractor_used="marker")
        MockMarker.return_value = mock_marker_instance

        result = await FallbackManager.extract_with_fallback(content, "application/pdf", "test.pdf")

    assert result.content == "Marker Success"
    assert result.extractor_used == "marker"

    # Verify call order
    mock_primary.extract.assert_called_once()
    mock_marker_instance.extract.assert_called_once()
