"""
PyMuPDF4LLM Extractor
=====================

Fast-path extractor for clean PDFs using pymupdf4llm.
"""

import logging
import re
import time

# Ideally we import these, but for safety in case not installed, we can handle import error?
# For now assume implementation plan requirement is met (packages installed or will be).
try:
    import pymupdf4llm
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

# Try to import layout engine if available (activates automatically on import)
if HAS_PYMUPDF:
    try:
        import pymupdf_layout
        logger.info("pymupdf_layout is available and activated.")
    except ImportError:
        logger.debug("pymupdf_layout not found, using standard pymupdf4llm.")

from src.core.ingestion.infrastructure.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


def _extract_title_from_content(content: str) -> str | None:
    """Extract title from the first heading in markdown content."""
    if not content:
        return None
    
    # Try to find the first markdown heading (# Title or ## Title)
    heading_match = re.search(r'^#{1,2}\s+(.+?)$', content, re.MULTILINE)
    if heading_match:
        title = heading_match.group(1).strip()
        # Clean up common artifacts
        title = re.sub(r'\*+', '', title)  # Remove bold markers
        title = title.strip()
        if title and len(title) > 2:
            return title[:200]  # Limit length
    
    # Fallback: use first non-empty line if it looks like a title
    for line in content.split('\n')[:10]:
        line = line.strip()
        if line and len(line) > 3 and len(line) < 150 and not line.startswith('|'):
            # Skip lines that look like metadata or table rows
            if not re.match(r'^[\d\-/.]+$', line):
                return line
    
    return None


class PyMuPDFExtractor(BaseExtractor):
    """
    Extractor using pymupdf4llm for markdown extraction from PDFs.
    """

    @property
    def name(self) -> str:
        return "pymupdf4llm"

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract content from PDF bytes.
        """
        if not HAS_PYMUPDF:
            raise ImportError("pymupdf4llm is not installed.")

        if not file_type.lower().endswith("pdf") and "pdf" not in file_type.lower():
             # PyMuPDF4LLM basically only does PDF.
             # We might support generic file types if supported by lib, but mostly PDF.
             pass

        start_time = time.time()

        # pymupdf4llm.to_markdown accepts bytes or path
        # It's a synchronous blocking call, so we should offload to thread if possible.
        # But for this V1, direct call or simplistic async wrapper.

        # We need to write bytes to temp file because pymupdf4llm might need path or handle bytes directly?
        # Checking docs: pymupdf4llm.to_markdown(doc) or path.
        # fitz.open("pdf", stream=file_content)

        import fitz

        try:
            # Open document from memory
            doc = fitz.open(stream=file_content, filetype="pdf")

            # Extract markdown
            # pymupdf4llm.to_markdown(doc=doc)
            md_text = pymupdf4llm.to_markdown(doc)

            # It returns a string.
            # Metadata from PDF (may contain empty strings)
            raw_metadata = doc.metadata if doc.metadata else {}
            page_count = doc.page_count

            # Clean up metadata: filter out empty string values
            metadata = {k: v for k, v in raw_metadata.items() if v and str(v).strip()}
            
            # Always add page count
            metadata["page_count"] = page_count
            
            # If title is missing, try to extract from content
            if not metadata.get("title"):
                extracted_title = _extract_title_from_content(md_text)
                if extracted_title:
                    metadata["title"] = extracted_title
                    metadata["title_source"] = "extracted_from_content"

            elapsed = (time.time() - start_time) * 1000

            return ExtractionResult(
                content=md_text,
                tables=[], # PyMuPDF4LLM integrates tables into markdown text usually
                metadata=metadata,
                extractor_used=self.name,
                confidence=0.95, # High confidence for clean text
                extraction_time_ms=elapsed
            )

        except Exception as e:
            logger.error(f"PyMuPDF extraction failed: {e}")
            raise RuntimeError(f"PyMuPDF extraction failed: {e}") from e

