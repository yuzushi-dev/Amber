"""
PaddleOCR Extractor
===================

OCR extractor for non-Latin scripts and dense text.
"""

import logging
import os
import tempfile
import time

from src.core.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)

try:
    from paddleocr import PaddleOCR
    HAS_PADDLEOCR = True
except ImportError:
    HAS_PADDLEOCR = False


class PaddleOCRExtractor(BaseExtractor):
    """
    OCR extractor using PaddleOCR.
    Excellent for non-Latin scripts (Chinese, Japanese, Korean, Arabic)
    and dense text layouts.
    """

    def __init__(self, lang: str = "en"):
        """
        Initialize PaddleOCR extractor.

        Args:
            lang: Language code (en, ch, japan, korean, arabic, etc.)
        """
        self.lang = lang
        self._ocr = None

    @property
    def name(self) -> str:
        return "paddleocr"

    def _get_ocr(self):
        """Lazy load OCR model."""
        if self._ocr is None and HAS_PADDLEOCR:
            self._ocr = PaddleOCR(use_angle_cls=True, lang=self.lang, show_log=False)
        return self._ocr

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract text using PaddleOCR.
        """
        if not HAS_PADDLEOCR:
            raise ImportError("paddleocr is required for PaddleOCR extraction")

        start_time = time.time()

        # Check if it's a PDF - need to convert to images first
        is_pdf = "pdf" in file_type.lower()

        with tempfile.NamedTemporaryFile(suffix=".pdf" if is_pdf else ".png", delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            ocr = self._get_ocr()

            if is_pdf:
                # For PDFs, use pdf2image
                try:
                    import pdf2image
                    images = pdf2image.convert_from_path(tmp_path)
                    texts = []
                    confidences = []

                    for i, img in enumerate(images):
                        # Save image temporarily
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_tmp:
                            img.save(img_tmp.name)
                            result = ocr.ocr(img_tmp.name, cls=True)
                            os.remove(img_tmp.name)

                        page_text = []
                        page_conf = []

                        if result and result[0]:
                            for line in result[0]:
                                text = line[1][0]
                                conf = line[1][1]
                                page_text.append(text)
                                page_conf.append(conf)

                        texts.append(f"--- Page {i + 1} ---\n" + "\n".join(page_text))
                        if page_conf:
                            confidences.append(sum(page_conf) / len(page_conf))

                    full_text = "\n\n".join(texts)
                    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
                    page_count = len(images)

                except ImportError as e:
                    raise ImportError("pdf2image is required for PDF processing with PaddleOCR") from e
            else:
                # For images, direct OCR
                result = ocr.ocr(tmp_path, cls=True)

                texts = []
                confidences = []

                if result and result[0]:
                    for line in result[0]:
                        texts.append(line[1][0])
                        confidences.append(line[1][1])

                full_text = "\n".join(texts)
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
                page_count = 1

            elapsed = (time.time() - start_time) * 1000

            return ExtractionResult(
                content=full_text,
                tables=[],
                metadata={
                    "page_count": page_count,
                    "ocr_engine": "paddleocr",
                    "language": self.lang,
                },
                extractor_used=self.name,
                confidence=avg_confidence,
                extraction_time_ms=elapsed
            )

        except Exception as e:
            logger.error(f"PaddleOCR extraction failed: {e}")
            raise RuntimeError(f"PaddleOCR extraction failed: {e}") from e
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
