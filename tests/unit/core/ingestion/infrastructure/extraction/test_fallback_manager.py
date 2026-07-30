"""Unit coverage for the local extraction fallback chain."""

from unittest.mock import AsyncMock, patch

import pytest

from src.core.ingestion.infrastructure.extraction.base import ExtractionResult
from src.core.ingestion.infrastructure.extraction.fallback import FallbackManager


@pytest.mark.asyncio
async def test_fallback_chain_primary_success():
    """The primary extractor short-circuits the fallback chain."""
    mock_primary = AsyncMock()
    mock_primary.name = "primary"
    mock_primary.extract.return_value = ExtractionResult(
        content="Primary Success", extractor_used="primary"
    )

    with patch(
        "src.core.ingestion.infrastructure.extraction.registry.ExtractorRegistry.get_extractor",
        return_value=mock_primary,
    ):
        result = await FallbackManager.extract_with_fallback(
            b"Simple content", "application/pdf", "test.pdf"
        )

    assert result.content == "Primary Success"
    assert result.extractor_used == "primary"
    mock_primary.extract.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_chain_without_retired_marker_reports_primary_failure():
    """A failed primary has no retired Marker fallback path."""
    mock_primary = AsyncMock()
    mock_primary.name = "primary"
    mock_primary.extract.side_effect = RuntimeError("Primary Failed")

    with patch(
        "src.core.ingestion.infrastructure.extraction.registry.ExtractorRegistry.get_extractor",
        return_value=mock_primary,
    ), pytest.raises(RuntimeError, match="Primary Failed"):
        await FallbackManager.extract_with_fallback(
            b"Complex content", "application/pdf", "test.pdf"
        )

    mock_primary.extract.assert_called_once()
