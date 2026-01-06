"""
Unstructured Extractor
======================

Backstop extractor for generic files using the unstructured library.
"""

import logging
import time

try:
    from unstructured.partition.auto import partition
    HAS_UNSTRUCTURED = True
except ImportError:
    HAS_UNSTRUCTURED = False

from src.core.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class UnstructuredExtractor(BaseExtractor):
    """
    Extractor using 'unstructured' library.
    Supports: docx, txt, html, email, etc.
    """

    @property
    def name(self) -> str:
        return "unstructured"

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract content using Unstructured's auto-partition.
        """
        if not HAS_UNSTRUCTURED:
            raise ImportError("unstructured is not installed.")

        start_time = time.time()

        # Unstructured usually works best with files or file-likes
        import io
        file = io.BytesIO(file_content)

        try:
            # We assume blocking call here.
            # partition auto-detects based on content/extension if provided.
            # providing content_type would be good, but auto works well.
            # We pass file object. We can also pass content_type to help it.
            # Convert file_type to something unstructured understands if needed,
            # generally standard MIME types work.

            # Map simple extensions to MIME if needed, but registry passes MIME or ext.

            kwargs_partition = {"file": file}
            if "/" in file_type:
                kwargs_partition["content_type"] = file_type

            elements = partition(**kwargs_partition)

            # Combine elements into text
            # We want markdown ideally.
            # Unstructured has element types. Simple join for now,
            # or try to respect hierarchy (Header vs NarrativeText)

            text_parts = []
            for element in elements:
                text_parts.append(str(element))

            content = "\n\n".join(text_parts)

            elapsed = (time.time() - start_time) * 1000

            return ExtractionResult(
                content=content,
                tables=[], # Tables parsing in unstructured requires strategy="hi_res" usually
                metadata={},
                extractor_used=self.name,
                confidence=0.8, # Generic confidence
                extraction_time_ms=elapsed
            )

        except Exception as e:
            logger.error(f"Unstructured extraction failed: {e}")
            raise RuntimeError(f"Unstructured extraction failed: {e}") from e
