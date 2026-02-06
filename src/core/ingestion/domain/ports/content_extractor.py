from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ExtractionResult:
    """Normalized extraction result returned by content extractors."""

    content: str
    tables: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    extractor_used: str = ""
    confidence: float = 1.0
    extraction_time_ms: float = 0.0


class ContentExtractorPort(Protocol):
    """Port for extracting content from files."""

    async def extract(
        self, file_content: bytes, mime_type: str, filename: str
    ) -> ExtractionResult: ...


_content_extractor: ContentExtractorPort | None = None


def set_content_extractor(extractor: ContentExtractorPort | None) -> None:
    global _content_extractor
    _content_extractor = extractor


def get_content_extractor() -> ContentExtractorPort:
    if _content_extractor is None:
        raise RuntimeError(
            "Content extractor not configured. Call set_content_extractor() at startup."
        )
    return _content_extractor
