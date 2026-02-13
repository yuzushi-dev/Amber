import pytest
from unittest.mock import MagicMock, patch

from src.core.ingestion.infrastructure.extraction.local.kreuzberg_extractor import (
    HAS_KREUZBERG,
    KreuzbergExtractor,
)


@pytest.mark.asyncio
async def test_kreuzberg_extractor_flow():
    """Test KreuzbergExtractor async wrapper + argument mapping."""
    if not HAS_KREUZBERG:
        pytest.skip("Kreuzberg not installed")

    extractor = KreuzbergExtractor()
    assert extractor.name == "kreuzberg"

    with patch(
        "src.core.ingestion.infrastructure.extraction.local.kreuzberg_extractor.extract_bytes_sync"
    ) as mock_extract:
        mock_result = MagicMock()
        mock_result.content = "Mocked Markdown Content"
        mock_result.metadata = {"page_count": 5}
        mock_extract.return_value = mock_result

        file_content = b"PDF_BYTES"
        result = await extractor.extract(file_content, file_type="pdf")

        assert result.content == "Mocked Markdown Content"
        assert result.metadata["page_count"] == 5
        assert result.extractor_used == "kreuzberg"

        args, kwargs = mock_extract.call_args
        assert args[0] == file_content
        assert args[1] == "application/pdf"

        cfg = kwargs.get("config")
        assert cfg is not None

        output_format = getattr(cfg, "output_format", None)
        # output_format can be an enum (preferred) or a plain string.
        if hasattr(output_format, "value"):
            assert str(output_format.value).lower() == "markdown"
        elif hasattr(output_format, "name"):
            assert str(output_format.name).lower() == "markdown"
        else:
            assert str(output_format).lower() == "markdown"
