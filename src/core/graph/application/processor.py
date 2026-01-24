import asyncio
import logging
from typing import TYPE_CHECKING

from src.core.graph.application.writer import graph_writer
from src.core.graph.domain.ports.graph_extractor import GraphExtractorPort, get_graph_extractor

if TYPE_CHECKING:
    from src.core.ingestion.domain.chunk import Chunk

logger = logging.getLogger(__name__)

class GraphProcessor:
    """
    Orchestrator for Graph Extraction and Persistence.
    Takes chunks, runs extraction, and writes to Neo4j.
    """

    def __init__(self, graph_extractor: GraphExtractorPort | None = None):
        self.extractor = graph_extractor
        self.writer = graph_writer

    async def process_chunks(self, chunks: list["Chunk"], tenant_id: str, filename: str = None):
        """
        Process a list of chunks to extract and write graph data.
        """
        if not chunks:
            return

        logger.info(f"Starting graph processing for {len(chunks)} chunks")

        # Concurrency control
        # 5 concurrent requests is a safe default for economy tier
        sem = asyncio.Semaphore(5)

        async def _process_one(chunk):
            async with sem:
                try:
                    # check length, if too short maybe skip?
                    if len(chunk.content) < 50:
                        return

                    extractor = self.extractor or get_graph_extractor()
                    result = await extractor.extract(chunk.content)

                    if result.entities:
                        await self.writer.write_extraction_result(
                            document_id=chunk.document_id,
                            chunk_id=chunk.id,
                            tenant_id=tenant_id,
                            result=result,
                            filename=filename
                        )
                except Exception as e:
                    logger.error(f"Graph processing failed for chunk {chunk.id}: {e}")

        tasks = [_process_one(c) for c in chunks]
        await asyncio.gather(*tasks)
        logger.info(f"Completed graph processing for {len(chunks)} chunks")

graph_processor = GraphProcessor()
