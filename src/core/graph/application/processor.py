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

    async def process_chunks(
        self,
        chunks: list["Chunk"],
        tenant_id: str,
        filename: str = None,
        tenant_config: dict | None = None,
    ):
        """
        Process a list of chunks to extract and write graph data.
        """
        if not chunks:
            return

        logger.info(f"Starting graph processing for {len(chunks)} chunks")

        # Concurrency control
        # 5 concurrent requests is a safe default for economy tier
        sem = asyncio.Semaphore(5)

        # Metrics Aggregation
        total_tokens = 0
        total_cost = 0.0
        total_entities = 0
        total_rels = 0
        
        async def _process_one(chunk):
            nonlocal total_tokens, total_cost, total_entities, total_rels
            async with sem:
                try:
                    # check length, if too short maybe skip?
                    if len(chunk.content) < 50:
                        return

                    extractor = self.extractor or get_graph_extractor()
                    
                    # We create a label but we DON'T track per-chunk in DB anymore
                    # The extractor will return usage stats instead
                    result = await extractor.extract(
                        chunk.content,
                        chunk_id=chunk.id,
                        track_usage=False,
                        tenant_config=tenant_config,
                    )
                    
                    # Accumulate stats logic should be thread-safe if running concurrently?
                    # asyncio is single-threaded cooperatively, so simple += is fine unless we await during update.
                    # Updates here are simple ops.
                    if result.usage:
                        total_tokens += result.usage.total_tokens
                        total_cost += result.usage.cost_estimate
                    
                    total_entities += len(result.entities)
                    total_rels += len(result.relationships)

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
        
        # Log consolidated metrics
        try:
            from src.shared.kernel.runtime import get_settings
            from src.core.admin_ops.application.metrics.collector import MetricsCollector
            from src.shared.identifiers import generate_query_id
            
            settings = get_settings()
            collector = MetricsCollector(redis_url=settings.db.redis_url)
            
            label = f"Graph Extraction: {filename} ({len(chunks)} chunks)"
            # Log usage
            # We construct a synthetic query metric
            # But track_query expects to wrap a call. 
            # We can use it as a context manager and just set values.
            async with collector.track_query(generate_query_id(), tenant_id, label) as qm:
                qm.operation = "extraction"
                qm.tokens_used = total_tokens
                qm.cost_estimate = total_cost
                # Input/Output split is harder to track precisely aggregated without more vars, 
                # but total tokens/cost is what users care about most.
                # We can assume roughly 70/30 split or just leave input/output 0 if usage object didn't split well?
                # Actually usage object splits it. We could track input/output separately too.
                # For brevity, let's just log totals.
                
                qm.response = f"Extracted {total_entities} entities, {total_rels} relationships from {len(chunks)} chunks."
                qm.success = True
                
        except Exception as e:
             logger.error(f"Failed to log aggregated graph metrics: {e}")

        logger.info(f"Completed graph processing for {len(chunks)} chunks")

graph_processor = GraphProcessor()
