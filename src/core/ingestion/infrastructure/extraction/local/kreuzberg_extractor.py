"""
Kreuzberg Extractor
===================

Extractor using Kreuzberg for high-performance extraction (PDF, Images, etc).
"""

import logging
import time

from src.core.ingestion.infrastructure.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)

try:
    from kreuzberg import ExtractionConfig, OutputFormat, extract_bytes_sync

    HAS_KREUZBERG = True
except ImportError:
    HAS_KREUZBERG = False


def _normalize_mime(file_type: str) -> str:
    """Convert an extension-like file_type (e.g. pdf) to a MIME type."""
    if not file_type:
        return "application/octet-stream"

    if "/" in file_type:
        return file_type

    ft = file_type.lower().lstrip(".")
    if ft == "pdf":
        return "application/pdf"
    if ft in ("jpg", "jpeg"):
        return "image/jpeg"
    if ft == "png":
        return "image/png"

    return "application/octet-stream"


class KreuzbergExtractor(BaseExtractor):
    """Extractor using the Kreuzberg library."""

    @property
    def name(self) -> str:
        return "kreuzberg"

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """Extract content from file bytes using Kreuzberg."""
        if not HAS_KREUZBERG:
            raise ImportError("kreuzberg is not installed.")

        start_time = time.time()

        try:
            mime_type = _normalize_mime(file_type)
            config = ExtractionConfig(output_format=OutputFormat.MARKDOWN)

            # extract_bytes_sync(data, mime_type, config=...)
            result = extract_bytes_sync(file_content, mime_type, config=config)

            elapsed = (time.time() - start_time) * 1000

            return ExtractionResult(
                content=result.content,
                tables=[],  # Markdown mode embeds tables in the content
                metadata=result.metadata or {},
                extractor_used=self.name,
                confidence=0.9,
                extraction_time_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"Kreuzberg extraction failed: {e}")
            raise RuntimeError(f"Kreuzberg extraction failed: {e}") from e
