"""
Mistral OCR Extractor
=====================

High-quality API-based extraction using Mistral.
"""

from src.core.ingestion.infrastructure.extraction.base import BaseExtractor, ExtractionResult
from src.core.ingestion.infrastructure.extraction.config import extraction_settings


class MistralOCRExtractor(BaseExtractor):
    """
    Extractor using Mistral's OCR capabilities via API.
    """

    @property
    def name(self) -> str:
        return "mistral-ocr"

    async def extract(self, file_content: bytes, mime_type: str, **kwargs) -> ExtractionResult:
        """
        Extract content using Mistral API.
        """
        if not extraction_settings.mistral_ocr_enabled:
            raise ValueError("Mistral OCR is disabled by configuration.")
        raise RuntimeError(
            "Mistral OCR is not implemented; disable MISTRAL_OCR_ENABLED until "
            "a contract-tested integration exists."
        )
