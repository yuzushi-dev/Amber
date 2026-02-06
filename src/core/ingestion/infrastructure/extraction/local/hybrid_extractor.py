"""
Hybrid Marker Extractor
=======================

Intelligently switches between fast text extraction (PyMuPDF) and
high-quality OCR (Marker) on a per-page basis.
"""

import logging
import os
import re
import tempfile
import time

import fitz  # PyMuPDF
import pymupdf4llm

from src.core.ingestion.infrastructure.extraction.base import BaseExtractor, ExtractionResult
from src.core.ingestion.infrastructure.extraction.config import extraction_settings
from src.core.ingestion.infrastructure.extraction.local.marker_extractor import MarkerExtractor

logger = logging.getLogger(__name__)


def _extract_title_from_content(content: str) -> str | None:
    """Extract title from the first heading in markdown content."""
    if not content:
        return None

    # Try to find the first markdown heading (# Title or ## Title)
    heading_match = re.search(r"^#{1,2}\s+(.+?)$", content, re.MULTILINE)
    if heading_match:
        title = heading_match.group(1).strip()
        # Clean up common artifacts
        title = re.sub(r"\*+", "", title)  # Remove bold markers
        title = title.strip()
        if title and len(title) > 2:
            return title[:200]  # Limit length

    # Fallback: use first non-empty line if it looks like a title
    for line in content.split("\n")[:10]:
        line = line.strip()
        if line and len(line) > 3 and len(line) < 150 and not line.startswith("|"):
            # Skip lines that look like metadata or table rows
            if not re.match(r"^[\d\-/.]+$", line):
                return line

    return None


class HybridMarkerExtractor(BaseExtractor):
    """
    Extractor that applies OCR selectively to image-only pages.
    """

    def __init__(self):
        self._marker = None

    @property
    def name(self) -> str:
        return "hybrid_marker"

    def _get_marker(self) -> MarkerExtractor:
        """Lazy load marker extractor."""
        if self._marker is None:
            self._marker = MarkerExtractor()
        return self._marker

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract content using a hybrid strategy.
        """
        start_time = time.time()

        # 1. Open Document
        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
        except Exception as e:
            raise ValueError(f"Failed to open PDF: {e}") from e

        # 2. Analyze Pages
        text_pages = []
        ocr_pages = []

        threshold = extraction_settings.ocr_text_density_threshold

        for i, page in enumerate(doc):
            text = page.get_text()
            has_images = len(page.get_images()) > 0
            text_len = len(text.strip())

            # Heuristic: Small amount of text + Images -> Potentially Scanned
            if text_len < threshold and has_images:
                ocr_pages.append(i)
            else:
                text_pages.append(i)

        logger.info(f"Hybrid Analysis: {len(text_pages)} text pages, {len(ocr_pages)} OCR pages")

        # Get raw metadata and clean up empty strings
        raw_metadata = doc.metadata if doc.metadata else {}
        metadata = {k: v for k, v in raw_metadata.items() if v and str(v).strip()}
        metadata["page_count"] = doc.page_count

        # 3. Process Pages
        results = {}  # page_index -> text content

        # 3a. Fast Extraction (Text Pages)
        if text_pages:
            # We use pymupdf4llm for high quality markdown
            # It supports 'pages' argument to process subset
            try:
                # pymupdf4llm expects a Document object or path.
                # It returns the markdown string for the selected pages.
                # However, we need to stitch them in order.
                # pymupdf4llm doesn't return per-page dict, it joins them.
                # So we stick to a loop or per-page call if we want strict ordering mixed with OCR results.
                # Calling to_markdown per page might be slightly inefficient overhead-wise but safe.

                for page_idx in text_pages:
                    # We can use the global helper or the method.
                    # pymupdf4llm.to_markdown(doc, pages=[page_idx]) gives the content for that page.
                    page_md = pymupdf4llm.to_markdown(doc, pages=[page_idx])
                    results[page_idx] = page_md

            except Exception as e:
                logger.error(f"Text extraction failed: {e}")
                # Fallback to simple get_text
                for page_idx in text_pages:
                    results[page_idx] = doc[page_idx].get_text()

        # 3b. Heavy Extraction (OCR Pages)
        if ocr_pages:
            marker = self._get_marker()

            # We must save each page to a temporary PDF for Marker
            for page_idx in ocr_pages:
                try:
                    # Create single-page PDF
                    new_doc = fitz.open()
                    new_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)

                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        # Write to temp file
                        new_doc.save(tmp.name)
                        tmp_path = tmp.name

                    try:
                        # We need to manually call the raw marker function?
                        # Or use the MarkerExtractor.extract() with file content?
                        # MarkerExtractor.extract() takes bytes.
                        # We can pass the bytes of the new single-page PDF.
                        pdf_bytes = new_doc.tobytes()

                        # Use the extract method (it handles temp file creation internally too,
                        # which is double IO, but keeps abstraction clean).
                        # Optimization: Refactor MarkerExtractor later to accept path.
                        # For now, double IO for these few pages is acceptable.

                        result = await marker.extract(pdf_bytes, "pdf")
                        results[page_idx] = result.content

                        # Merge metadata (images mainly)
                        # We might want to capture images? Marker returns image paths in a dict usually?
                        # Our base MarkerExtractor implementation returns images in result.images.
                        # We should collect them.

                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)

                        new_doc.close()

                except Exception as e:
                    logger.error(f"OCR failed for page {page_idx}: {e}")
                    results[page_idx] = "[OCR Failed]"

        # 4. Stitch Results
        final_content = []
        sorted_indices = sorted(results.keys())

        for idx in sorted_indices:
            # Add page marker if desired, or just join
            # PyMuPDF4LLM often adds `-----` or headers.
            content = results[idx]
            final_content.append(content)

        full_text = "\n\n".join(final_content)

        # 5. Extract title from content if missing in PDF metadata
        if not metadata.get("title"):
            extracted_title = _extract_title_from_content(full_text)
            if extracted_title:
                metadata["title"] = extracted_title
                metadata["title_source"] = "extracted_from_content"

        elapsed = (time.time() - start_time) * 1000

        return ExtractionResult(
            content=full_text,
            tables=[],  # Populated if we parse them deeply
            images=[],  # We could aggregate images from OCR pages
            metadata=metadata,
            extractor_used=self.name,
            confidence=0.85,
            extraction_time_ms=elapsed,
        )
