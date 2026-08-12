"""
Extraction Configuration
========================

Configuration settings for document extraction and quality gates.
"""

import os
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings


class ExtractionSettings(BaseSettings):
    """
    Timeout and configuration for extraction tools.
    """

    # Timeouts in seconds
    default_timeout: int = 60
    heavy_timeout: int = 300  # For large local documents

    # PyMuPDF
    pymupdf_enabled: bool = False

    # Unstructured
    unstructured_enabled: bool = True

    # Docling (Table specialist)
    docling_enabled: bool = False

    # Tesseract (Legacy OCR)
    tesseract_enabled: bool = False

    # PaddleOCR (Non-latin scripts)
    paddleocr_enabled: bool = False

    # Kreuzberg (General purpose local)
    kreuzberg_enabled: bool = True

    # HTML → Markdown normalization (content scoping + MarkItDown).
    # Off by default: enable with HTML_MARKDOWN_ENABLED=true once validated.
    html_markdown_enabled: bool = False

    # Quality Gate Thresholds
    min_ocr_confidence: float = 0.7  # Minimum OCR confidence to accept
    min_content_density: float = 0.1  # Minimum chars per page to accept
    min_content_length: int = 100  # Minimum total character count

    # OCR Settings
    mistral_ocr_enabled: bool = False

    # Quality actions
    # Default OFF: when True, low-quality extractions stop at NEEDS_REVIEW, but no
    # endpoint yet releases NEEDS_REVIEW docs, so they would get stuck. Keep False
    # for zero-regression deploys; enable (env MARK_LOW_QUALITY_AS_NEEDS_REVIEW=true)
    # once a review/release workflow exists.
    mark_low_quality_as_needs_review: bool = False

    @model_validator(mode="before")
    @classmethod
    def reject_retired_marker_settings(cls, values: Any) -> Any:
        """Prevent stale Marker flags from silently changing extraction behavior."""
        retired_settings = {"marker_enabled", "hybrid_ocr_enabled"}
        configured_settings = set(values).intersection(retired_settings) if isinstance(values, dict) else set()
        configured_settings.update(
            setting for setting in retired_settings if setting.upper() in os.environ
        )
        if configured_settings:
            configured = ", ".join(sorted(configured_settings))
            raise ValueError(
                "Marker OCR support has been retired; remove the retired setting(s): "
                f"{configured}"
            )
        return values

    @model_validator(mode="after")
    def reject_unimplemented_mistral_ocr(self) -> "ExtractionSettings":
        """Do not boot with an OCR backend that still has no real extraction flow."""
        if self.mistral_ocr_enabled:
            raise ValueError(
                "Mistral OCR is not available: the extraction flow is not implemented yet. "
                "Keep MISTRAL_OCR_ENABLED=false until a contract-tested API integration exists."
            )
        return self


extraction_settings = ExtractionSettings()
