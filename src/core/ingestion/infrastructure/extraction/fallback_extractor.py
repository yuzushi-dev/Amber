from src.core.ingestion.domain.ports.content_extractor import ContentExtractorPort, ExtractionResult
from src.core.ingestion.infrastructure.extraction.fallback import FallbackManager


class FallbackContentExtractor(ContentExtractorPort):
    """Adapter that uses the fallback manager to extract content."""

    async def extract(self, file_content: bytes, mime_type: str, filename: str) -> ExtractionResult:
        result = await FallbackManager.extract_with_fallback(
            file_content=file_content,
            mime_type=mime_type,
            filename=filename,
        )
        return ExtractionResult(
            content=result.content,
            tables=result.tables,
            images=result.images,
            metadata=result.metadata,
            extractor_used=result.extractor_used,
            confidence=result.confidence,
            extraction_time_ms=result.extraction_time_ms,
        )
