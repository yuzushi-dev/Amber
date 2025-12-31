"""
Fallback Manager
================

Orchestrates the fallback chain for document extraction.
"""

import logging
from typing import List, Type, Optional

from src.core.extraction.base import BaseExtractor, ExtractionResult
from src.core.extraction.registry import ExtractorRegistry
from src.core.extraction.config import extraction_settings
from src.core.extraction.local.marker_extractor import MarkerExtractor
from src.core.extraction.api.mistral_ocr_extractor import MistralOCRExtractor

logger = logging.getLogger(__name__)


class FallbackManager:
    """
    Manages the execution of extraction fallback chains.
    """

    @classmethod
    async def extract_with_fallback(cls, file_content: bytes, mime_type: str, filename: str) -> ExtractionResult:
        """
        Extract content by trying a sequence of extractors.
        """
        chain = cls._build_chain(mime_type)
        
        errors = {}
        
        for extractor in chain:
            try:
                logger.info(f"Attempting extraction with {extractor.name} for {filename}")
                return await extractor.extract(
                    file_content=file_content, 
                    file_type=mime_type
                )
            except Exception as e:
                logger.warning(f"Extractor {extractor.name} failed for {filename}: {e}")
                errors[extractor.name] = str(e)
                continue
        
        # If all fail
        logger.error(f"All extractors failed for {filename}. Errors: {errors}")
        raise RuntimeError(f"Extraction failed after checking {len(chain)} tools. Details: {errors}")

    @classmethod
    def _build_chain(cls, mime_type: str) -> List[BaseExtractor]:
        """
        Build the prioritized list of extractors based on configuration and file type.
        """
        chain: List[BaseExtractor] = []
        
        # 1. Primary (Fast Path)
        try:
            primary = ExtractorRegistry.get_extractor(mime_type)
            chain.append(primary)
        except ValueError:
            pass # No primary found? Should fall back to unstructured usually.
            
        # 2. Secondary (Marker - Heavy Local)
        # Typically for PDFs or Images. 
        if "pdf" in mime_type.lower() and extraction_settings.marker_enabled:
             chain.append(MarkerExtractor())
             
        # 3. Tertiary (Mistral OCR - API)
        # Final resort
        if extraction_settings.mistral_ocr_enabled:
            chain.append(MistralOCRExtractor())
            
        return chain
