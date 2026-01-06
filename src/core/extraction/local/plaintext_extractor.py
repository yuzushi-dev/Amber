"""
Plain Text Extractor
====================

Simple extractor for plain text files (.txt, .md).
"""

import logging
import time

from src.core.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class PlainTextExtractor(BaseExtractor):
    """
    Extracts content from plain text files.
    """

    name = "plaintext"

    def is_available(self) -> bool:
        """Always available - no dependencies."""
        return True

    async def extract(self, file_content: bytes, file_type: str = "") -> ExtractionResult:
        """
        Extract text content from plain text files.

        Args:
            file_content: Raw file bytes
            file_type: MIME type (ignored for plain text)

        Returns:
            ExtractionResult with extracted text
        """
        start_time = time.time()

        try:
            # Try common encodings
            text = None
            for encoding in ["utf-8", "utf-16", "latin-1"]:
                try:
                    text = file_content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue

            if text is None:
                text = file_content.decode("utf-8", errors="replace")

            # Basic markdown detection for metadata
            is_markdown = file_type in ("text/markdown", "text/x-markdown")

            extraction_time = (time.time() - start_time) * 1000

            logger.info(f"PlainTextExtractor extracted {len(text)} characters")

            return ExtractionResult(
                content=text.strip(),
                tables=[],
                images=[],
                metadata={
                    "encoding": "utf-8",
                    "is_markdown": is_markdown,
                    "char_count": len(text)
                },
                extractor_used=self.name,
                confidence=1.0,
                extraction_time_ms=extraction_time
            )
        except Exception as e:
            logger.error(f"PlainTextExtractor failed: {e}")
            raise

