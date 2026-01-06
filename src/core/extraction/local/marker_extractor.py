"""
Marker Extractor
================

High-fidelity PDF extraction using the marker-pdf library.
"""

import logging
import time

try:
    # marker-pdf exposes main functions.
    # Usually `from marker.convert import convert_single_pdf`
    # We'll assume the library is installed or handle import error.
    from marker.convert import convert_single_pdf
    from marker.models import load_all_models
    HAS_MARKER = True
except ImportError:
    HAS_MARKER = False

from src.core.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class MarkerExtractor(BaseExtractor):
    """
    Extractor using 'marker-pdf' for high-quality layout analysis and OCR.
    Good for scientific papers, complex layouts, math.
    """

    def __init__(self):
        self._model_lst = None

    @property
    def name(self) -> str:
        return "marker"

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract content using Marker.
        """
        if not HAS_MARKER:
            raise ImportError("marker-pdf is not installed.")

        start_time = time.time()

        # Marker requires a file path usually.
        # We'll write to a temp file.
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            # Lazy load models
            if self._model_lst is None:
                # This might be slow on first call
                # load_all_models returns (model_list)
                self._model_lst = load_all_models()

            # convert_single_pdf is sync/blocking.
            # returns (full_text, images, out_meta)
            full_text, images, out_meta = convert_single_pdf(
                tmp_path,
                self._model_lst,
                max_pages=None, # Extract all
                parallel_factor=1 # Single threaded within this process
            )

            elapsed = (time.time() - start_time) * 1000

            return ExtractionResult(
                content=full_text,
                tables=[], # Marker integrates tables into text (markdown tables)
                images=images, # Marker returns image paths/data
                metadata=out_meta if out_meta else {},
                extractor_used=self.name,
                confidence=0.9, # High confidence generally
                extraction_time_ms=elapsed
            )

        except Exception as e:
            logger.error(f"Marker extraction failed: {e}")
            raise RuntimeError(f"Marker extraction failed: {e}") from e
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
