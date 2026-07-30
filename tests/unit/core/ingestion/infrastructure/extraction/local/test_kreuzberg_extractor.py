from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw, ImageFont

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
        result = await extractor.extract(file_content, mime_type="pdf")

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

        assert cfg.ocr.backend == "tesseract"


@pytest.mark.asyncio
async def test_kreuzberg_extractor_rejects_empty_content():
    """Never mark an image-only document as extracted when OCR returns no text."""
    if not HAS_KREUZBERG:
        pytest.skip("Kreuzberg not installed")

    with patch(
        "src.core.ingestion.infrastructure.extraction.local.kreuzberg_extractor.extract_bytes_sync"
    ) as mock_extract:
        mock_result = MagicMock()
        mock_result.content = " \n\t"
        mock_result.metadata = {}
        mock_extract.return_value = mock_result

        with pytest.raises(RuntimeError, match="no extractable content"):
            await KreuzbergExtractor().extract(b"IMAGE_ONLY_PDF", mime_type="pdf")


@pytest.mark.asyncio
async def test_kreuzberg_extractor_ocrs_image_only_pdf():
    """Exercise the deployed OCR stack with a raster-only PDF and no text layer."""
    if not HAS_KREUZBERG:
        pytest.skip("Kreuzberg not installed")

    image = Image.new("RGB", (1600, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=96)
    draw.text((100, 170), "AMBER SCANNED 7429", fill="black", font=font)
    pdf = BytesIO()
    image.save(pdf, format="PDF", resolution=150)

    result = await KreuzbergExtractor().extract(
        pdf.getvalue(),
        mime_type="application/pdf",
    )

    normalized = " ".join(result.content.upper().split())
    assert "AMBER SCANNED 7429" in normalized
