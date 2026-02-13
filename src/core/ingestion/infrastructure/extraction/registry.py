"""
Extractor Registry
==================

Factory for getting the appropriate extractor for a file.
"""

from src.core.ingestion.infrastructure.extraction.base import BaseExtractor
from src.core.ingestion.infrastructure.extraction.config import extraction_settings
from src.core.ingestion.infrastructure.extraction.local.hybrid_extractor import (
    HybridMarkerExtractor,
)
from src.core.ingestion.infrastructure.extraction.local.plaintext_extractor import (
    PlainTextExtractor,
)
from src.core.ingestion.infrastructure.extraction.local.pymupdf_extractor import PyMuPDFExtractor
from src.core.ingestion.infrastructure.extraction.local.unstructured_extractor import (
    UnstructuredExtractor,
)
from src.core.ingestion.infrastructure.extraction.local.kreuzberg_extractor import (
    KreuzbergExtractor,
)


class ExtractorRegistry:
    """
    Registry for document extractors.
    """

    _extractors: dict[str, BaseExtractor] = {}

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
        if "text/plain" in mime_type.lower() or file_extension.lower() in (
            ".txt",
            ".md",
            ".markdown",
        ):
            return cls._get_instance("plaintext", PlainTextExtractor)

        if "text/markdown" in mime_type.lower() or "text/x-markdown" in mime_type.lower():
            return cls._get_instance("plaintext", PlainTextExtractor)

        # Code files (Python, Typescript, JS) - TreeSitter
        if file_extension.lower() in (".py", ".ts", ".tsx", ".js", ".jsx") or mime_type.lower() in (
            "text/x-python",
            "application/javascript",
            "application/typescript",
            "text/javascript",
        ):
            from src.core.ingestion.infrastructure.extraction.code.tree_sitter_extractor import (
                TreeSitterExtractor,
            )

            return cls._get_instance("treesitter", TreeSitterExtractor)

        # PDF
        if "pdf" in mime_type.lower() or file_extension.lower() == ".pdf":
            # Kreuzberg (High Performance / Local)
            if extraction_settings.kreuzberg_enabled:
                return cls._get_instance("kreuzberg", KreuzbergExtractor)

            # Hybrid OCR (Marker + PyMuPDF)
            if extraction_settings.hybrid_ocr_enabled:
                return cls._get_instance("hybrid", HybridMarkerExtractor)

            # PyMuPDF Standard
            if extraction_settings.pymupdf_enabled:
                return cls._get_instance("pymupdf", PyMuPDFExtractor)

        # Fallback / General
        if extraction_settings.unstructured_enabled:
            return cls._get_instance("unstructured", UnstructuredExtractor)

        raise ValueError(f"No suitable extractor found for {mime_type}")

    @classmethod
    def _get_instance(cls, name: str, verify_cls: type[BaseExtractor]) -> BaseExtractor:
        """Singleton-like access to extractors."""
        if name not in cls._extractors:
            cls._extractors[name] = verify_cls()
        return cls._extractors[name]
