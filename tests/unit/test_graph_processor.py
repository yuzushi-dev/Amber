from unittest.mock import AsyncMock, patch

import pytest

from src.core.graph.application.processor import GraphProcessor
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.generation.application.prompts.entity_extraction import ExtractionResult


@pytest.mark.asyncio
async def test_processor_flow():
    with patch("src.core.graph.application.processor.graph_writer") as mock_writer:
        mock_extractor = AsyncMock()
        ExtractionResult(entities=[], relationships=[])
        mock_result_with_entities = ExtractionResult(
            entities=[{"name": "E1", "type": "T", "description": "D"}],
            relationships=[]
        )
        mock_extractor.extract = AsyncMock(return_value=mock_result_with_entities)

        mock_writer.write_extraction_result = AsyncMock()

        chunks = [
            Chunk(id="c1", document_id="d1", content="Text 1 is long enough to be processed by the graph processor logic."),
            Chunk(id="c2", document_id="d1", content="Text 2 is also long enough to be processed by the graph processor logic.")
        ]

        processor = GraphProcessor(graph_extractor=mock_extractor)

        await processor.process_chunks(chunks, "tenant_1")

        assert mock_extractor.extract.call_count == 2
        assert mock_writer.write_extraction_result.call_count == 2
