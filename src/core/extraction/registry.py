"""
Extractor Registry
==================

Factory for getting the appropriate extractor for a file.
"""

from typing import Dict, Type

from src.core.extraction.base import BaseExtractor
from src.core.extraction.config import extraction_settings
from src.core.extraction.local.pymupdf_extractor import PyMuPDFExtractor
from src.core.extraction.local.unstructured_extractor import UnstructuredExtractor
from src.core.extraction.local.plaintext_extractor import PlainTextExtractor


class ExtractorRegistry:
    """
    Registry for document extractors.
    """
    
    _extractors: Dict[str, BaseExtractor] = {}

    @classmethod
    def get_extractor(cls, mime_type: str, file_extension: str = "") -> BaseExtractor:
        """
        Get the best extractor for the given file type.
        
        Args:
            mime_type: MIME type of the file
            file_extension: File extension (optional fallback)
            
        Returns:
            BaseExtractor: An instantiated extractor
        """
        # Primary routing logic
        
        # Plain text files (txt, md, etc.)
        if "text/plain" in mime_type.lower() or file_extension.lower() in (".txt", ".md", ".markdown"):
            return cls._get_instance("plaintext", PlainTextExtractor)
        
        # Markdown
        if "text/markdown" in mime_type.lower() or "text/x-markdown" in mime_type.lower():
            return cls._get_instance("plaintext", PlainTextExtractor)
        
        # PDF
        if "pdf" in mime_type.lower() or file_extension.lower() == ".pdf":
            # Prefer PyMuPDF if enabled
            if extraction_settings.pymupdf_enabled:
                return cls._get_instance("pymupdf", PyMuPDFExtractor)
        
        # Fallback / General
        if extraction_settings.unstructured_enabled:
            return cls._get_instance("unstructured", UnstructuredExtractor)
            
        raise ValueError(f"No suitable extractor found for {mime_type}")

    @classmethod
    def _get_instance(cls, name: str, verify_cls: Type[BaseExtractor]) -> BaseExtractor:
        """Singleton-like access to extractors."""
        if name not in cls._extractors:
            cls._extractors[name] = verify_cls()
        return cls._extractors[name]

