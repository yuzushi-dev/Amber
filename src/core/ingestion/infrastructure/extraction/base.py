"""
Base Extractor Interface
========================

Defines the abstract base class and result schema for all document extractors.
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    """
    Unified result structure for all extractors.
    """
    content: str = Field(..., description="Extracted markdown text")
    tables: list[dict] = Field(default_factory=list, description="Extracted structured tables")
    images: list[dict] = Field(default_factory=list, description="Extracted image metadata/content")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata (page count, author, etc)")
    extractor_used: str = Field(..., description="Name of the extractor used")
    confidence: float = Field(default=1.0, description="Confidence score 0.0-1.0")
    extraction_time_ms: float = Field(default=0.0, description="Time taken to extract in milliseconds")


class BaseExtractor(ABC):
    """
    Abstract base class for document extractors.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the extractor."""
        pass

    @abstractmethod
    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract content from file bytes.

        Args:
            file_content: Raw file bytes
            file_type: MIME type or extension (e.g. 'application/pdf', '.pdf')
            **kwargs: Additional arguments

        Returns:
            ExtractionResult: Standardized extraction result
        """
        pass
