import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.core.graph.processor import GraphProcessor
from src.core.models.chunk import Chunk
from src.core.models.document import Document # Required for SQLA relationship registry
from src.core.prompts.entity_extraction import ExtractionResult

@pytest.mark.asyncio
async def test_processor_flow():
    # Patch dependencies
    with patch("src.core.graph.processor.GraphExtractor") as MockExtractorClass, \
         patch("src.core.graph.processor.graph_writer") as mock_writer:
        
        # Setup Extractor Mock
        mock_extractor_instance = MockExtractorClass.return_value
        # Mock return of extract() with a valid ExtractionResult (even if empty)
        mock_result = ExtractionResult(entities=[], relationships=[])
        # We need a result with entities to trigger write (based on logic if result.entities)
        mock_result_with_entities = ExtractionResult(
            entities=[{"name": "E1", "type": "T", "description": "D"}], 
            relationships=[]
        )
        
        mock_extractor_instance.extract = AsyncMock(return_value=mock_result_with_entities)
        
        # Setup Writer Mock
        mock_writer.write_extraction_result = AsyncMock()
        
        # Setup Data
        # We need to ensure content length > 50 based on processor logic
        chunks = [
            Chunk(id="c1", document_id="d1", content="Text 1 is long enough to be processed by the graph processor logic."), 
            Chunk(id="c2", document_id="d1", content="Text 2 is also long enough to be processed by the graph processor logic.")
        ]
        
        # Initialize Processor
        # Note: GraphProcessor instantiation calls GraphExtractor(), so our patch MockExtractorClass works
        processor = GraphProcessor()
        # Ensure our specific mock instance is used (though patch should handle return_value)
        processor.extractor = mock_extractor_instance
        
        # Run
        await processor.process_chunks(chunks, "tenant_1")
        
        # Verify
        assert processor.extractor.extract.call_count == 2
        assert mock_writer.write_extraction_result.call_count == 2
