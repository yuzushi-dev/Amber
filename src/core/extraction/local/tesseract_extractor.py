"""
Tesseract Extractor
===================

Legacy OCR fallback using Tesseract.
"""

import time
import logging
import tempfile
import os
from typing import Any

from src.core.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image
    import pdf2image
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False


class TesseractExtractor(BaseExtractor):
    """
    OCR extractor using Tesseract.
    Good for scanned documents when other extractors fail.
    """

    @property
    def name(self) -> str:
        return "tesseract"

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract text using Tesseract OCR.
        """
        if not HAS_TESSERACT:
            raise ImportError("pytesseract and pdf2image are required for Tesseract extraction")
        
        start_time = time.time()
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name
        
        try:
            # Convert PDF to images
            images = pdf2image.convert_from_path(tmp_path)
            
            # Extract text from each page
            texts = []
            confidences = []
            
            for i, image in enumerate(images):
                # Get text with confidence data
                data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
                
                page_text = pytesseract.image_to_string(image)
                texts.append(f"--- Page {i + 1} ---\n{page_text}")
                
                # Calculate average confidence for this page
                page_confidences = [c for c in data.get("conf", []) if c > 0]
                if page_confidences:
                    confidences.append(sum(page_confidences) / len(page_confidences))
            
            full_text = "\n\n".join(texts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
            
            elapsed = (time.time() - start_time) * 1000
            
            return ExtractionResult(
                content=full_text,
                tables=[],
                metadata={
                    "page_count": len(images),
                    "ocr_engine": "tesseract",
                    "avg_confidence": avg_confidence,
                },
                extractor_used=self.name,
                confidence=avg_confidence / 100,  # Normalize to 0-1
                extraction_time_ms=elapsed
            )
            
        except Exception as e:
            logger.error(f"Tesseract extraction failed: {e}")
            raise RuntimeError(f"Tesseract extraction failed: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
