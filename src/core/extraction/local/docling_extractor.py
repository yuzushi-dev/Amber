"""
Docling Extractor
=================

Specialized extractor for complex table extraction.
"""

import logging
import os
import tempfile
import time

from src.core.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)

try:
    from docling.document_converter import DocumentConverter
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False


class DoclingExtractor(BaseExtractor):
    """
    Extractor using Docling for complex table extraction
    and structured document parsing.
    """

    def __init__(self):
        self._converter = None

    @property
    def name(self) -> str:
        return "docling"

    def _get_converter(self):
        """Lazy load converter."""
        if self._converter is None and HAS_DOCLING:
            self._converter = DocumentConverter()
        return self._converter

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract content using Docling.
        """
        if not HAS_DOCLING:
            raise ImportError("docling is required for Docling extraction")

        start_time = time.time()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            converter = self._get_converter()

            # Convert document
            result = converter.convert(tmp_path)

            # Export to markdown (preserves tables)
            markdown_content = result.document.export_to_markdown()

            # Extract tables separately
            tables = []
            for item in result.document.tables:
                tables.append({
                    "content": item.export_to_markdown(),
                    "page": getattr(item, "page", None),
                })

            elapsed = (time.time() - start_time) * 1000

            return ExtractionResult(
                content=markdown_content,
                tables=tables,
                metadata={
                    "page_count": len(result.pages) if hasattr(result, "pages") else 1,
                    "table_count": len(tables),
                },
                extractor_used=self.name,
                confidence=0.9,  # Docling is generally high quality
                extraction_time_ms=elapsed
            )

        except Exception as e:
            logger.error(f"Docling extraction failed: {e}")
            raise RuntimeError(f"Docling extraction failed: {e}") from e
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
