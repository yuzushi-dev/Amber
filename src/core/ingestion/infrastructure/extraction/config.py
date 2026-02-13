"""
Extraction Configuration
========================

Configuration settings for document extraction and quality gates.
"""

from pydantic_settings import BaseSettings


class ExtractionSettings(BaseSettings):
    """
    Timeout and configuration for extraction tools.
    """

    # Timeouts in seconds
    default_timeout: int = 60
    heavy_timeout: int = 300  # For OCR/Marker

    # PyMuPDF
    pymupdf_enabled: bool = False

    # Unstructured
    unstructured_enabled: bool = True

    # Marker (Heavy)
    marker_enabled: bool = False  # Disabled by default in basic setup

    # Docling (Table specialist)
    docling_enabled: bool = False

    # Tesseract (Legacy OCR)
    tesseract_enabled: bool = False

    # PaddleOCR (Non-latin scripts)
    paddleocr_enabled: bool = False

    # Kreuzberg (General purpose local)
    kreuzberg_enabled: bool = True

    # Quality Gate Thresholds
    min_ocr_confidence: float = 0.7  # Minimum OCR confidence to accept
    min_content_density: float = 0.1  # Minimum chars per page to accept
    min_content_length: int = 100  # Minimum total character count

    # Hybrid OCR Settings
    hybrid_ocr_enabled: bool = False
    mistral_ocr_enabled: bool = False
    ocr_text_density_threshold: int = 50  # Character count threshold for triggering OCR

    # Quality actions
    mark_low_quality_as_needs_review: bool = True


extraction_settings = ExtractionSettings()
