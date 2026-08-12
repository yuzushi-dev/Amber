"""Mistral OCR must remain fail-closed until its API flow exists."""

import pytest

from src.core.ingestion.infrastructure.extraction.api.mistral_ocr_extractor import (
    MistralOCRExtractor,
)
from src.core.ingestion.infrastructure.extraction.config import ExtractionSettings


def test_mistral_ocr_configuration_is_rejected_until_implemented():
    with pytest.raises(ValueError, match="Mistral OCR is not available"):
        ExtractionSettings(mistral_ocr_enabled=True)


@pytest.mark.asyncio
async def test_mistral_ocr_enabled_extraction_fails_without_placeholder(monkeypatch):
    from src.core.ingestion.infrastructure.extraction.api import mistral_ocr_extractor

    monkeypatch.setattr(mistral_ocr_extractor.extraction_settings, "mistral_ocr_enabled", True)

    with pytest.raises(RuntimeError, match="Mistral OCR is not implemented"):
        await MistralOCRExtractor().extract(b"source bytes", "application/pdf")
