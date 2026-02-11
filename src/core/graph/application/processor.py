import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from src.core.graph.application.concurrency_governor import ConcurrencyGovernor
from src.core.graph.application.sync_config import resolve_graph_sync_runtime_config
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
        tenant_config: dict[str, Any] | None = None,
    ):
        """
        Process a list of chunks to extract and write graph data.
        """
        if not chunks:
            return

        tenant_config = tenant_config or {}
        document_started = time.perf_counter()

        settings = None
        try:
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
        except Exception:
            settings = None

        graph_sync_config = resolve_graph_sync_runtime_config(
            settings=settings,
            tenant_config=tenant_config,
        )
        sem: asyncio.Semaphore | None = None
        governor: ConcurrencyGovernor | None = None
        concurrency_mode = "static"
        if graph_sync_config.adaptive_concurrency_enabled:
            governor = ConcurrencyGovernor(
                initial_limit=graph_sync_config.initial_concurrency,
                min_limit=1,
                max_limit=graph_sync_config.max_concurrency,
            )
            concurrency_mode = "adaptive"
        else:
            sem = asyncio.Semaphore(graph_sync_config.initial_concurrency)

        logger.info(
            (
                "Starting graph processing for %s chunks "
                "(profile=%s, mode=%s, initial_concurrency=%s, max_concurrency=%s)"
            ),
            len(chunks),
            graph_sync_config.profile,
            concurrency_mode,
            graph_sync_config.initial_concurrency,
            graph_sync_config.max_concurrency,
        )

        # Metrics Aggregation
        total_tokens = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        total_llm_calls = 0
        total_entities = 0
        total_rels = 0
        cache_hits = 0
        chunk_errors = 0

        total_chunks = len(chunks)

        async def _process_one(chunk, chunk_number: int):
            nonlocal total_tokens
            nonlocal total_input_tokens
            nonlocal total_output_tokens
            nonlocal total_cost
            nonlocal total_llm_calls
            nonlocal total_entities
            nonlocal total_rels
            nonlocal cache_hits
            nonlocal chunk_errors
            chunk_started = time.perf_counter()
            chunk_metrics: dict[str, Any] = {
                "event": "graph_sync_chunk_metrics",
                "document_id": chunk.document_id,
                "chunk_id": chunk.id,
                "chunk_number": chunk_number,
                "total_chunks": total_chunks,
                "chunk_progress": f"{chunk_number}/{total_chunks}",
                "profile": graph_sync_config.profile,
                "concurrency_mode": concurrency_mode,
                "extract_wait_ms": 0,
                "extract_ms": 0,
                "write_ms": 0,
                "llm_calls": 0,
                "tokens_total": 0,
                "entities": 0,
                "relationships": 0,
                "cache_hit": False,
                "error": None,
            }

            try:
                if len(chunk.content) < 50:
                    chunk_metrics["skip_reason"] = "short_chunk"
                    return

                extractor = self.extractor or get_graph_extractor()

                if governor is not None:
                    wait_ms = await governor.acquire()
                    chunk_metrics["extract_wait_ms"] = int(wait_ms)
                    extract_started = time.perf_counter()
                    had_error = False
                    try:
                        result = await extractor.extract(
                            chunk.content,
                            chunk_id=chunk.id,
                            track_usage=False,
                            tenant_id=tenant_id,
                            tenant_config=tenant_config,
                            chunk_number=chunk_number,
                            total_chunks=total_chunks,
                        )
                    except Exception:
                        had_error = True
                        raise
                    finally:
                        extract_ms = int((time.perf_counter() - extract_started) * 1000)
                        chunk_metrics["extract_ms"] = extract_ms
                        await governor.release(latency_ms=extract_ms, had_error=had_error)
                else:
                    wait_started = time.perf_counter()
                    async with sem:
                        extract_started = time.perf_counter()
                        chunk_metrics["extract_wait_ms"] = int((extract_started - wait_started) * 1000)

                        result = await extractor.extract(
                            chunk.content,
                            chunk_id=chunk.id,
                            track_usage=False,
                            tenant_id=tenant_id,
                            tenant_config=tenant_config,
                            chunk_number=chunk_number,
                            total_chunks=total_chunks,
                        )
                        chunk_metrics["extract_ms"] = int((time.perf_counter() - extract_started) * 1000)

                if result.usage:
                    total_tokens += result.usage.total_tokens
                    total_input_tokens += result.usage.input_tokens
                    total_output_tokens += result.usage.output_tokens
                    total_cost += result.usage.cost_estimate
                    total_llm_calls += result.usage.llm_calls

                    chunk_metrics["tokens_total"] = result.usage.total_tokens
                    chunk_metrics["llm_calls"] = result.usage.llm_calls
                    chunk_metrics["cache_hit"] = bool(getattr(result.usage, "cache_hit", False))

                total_entities += len(result.entities)
                total_rels += len(result.relationships)
                chunk_metrics["entities"] = len(result.entities)
                chunk_metrics["relationships"] = len(result.relationships)

                if chunk_metrics["cache_hit"]:
                    cache_hits += 1

                # Keep writes out of the LLM semaphore so the next extraction can start immediately.
                if result.entities:
                    write_started = time.perf_counter()
                    await self.writer.write_extraction_result(
                        document_id=chunk.document_id,
                        chunk_id=chunk.id,
                        tenant_id=tenant_id,
                        result=result,
                        filename=filename,
                    )
                    chunk_metrics["write_ms"] = int((time.perf_counter() - write_started) * 1000)

            except Exception as e:
                chunk_errors += 1
                chunk_metrics["error"] = str(e)
                logger.error(f"Graph processing failed for chunk {chunk.id}: {e}")
            finally:
                chunk_metrics["total_ms"] = int((time.perf_counter() - chunk_started) * 1000)
                logger.info("graph_sync_chunk_metrics %s", json.dumps(chunk_metrics, sort_keys=True))

        tasks = [_process_one(c, idx) for idx, c in enumerate(chunks, start=1)]
        await asyncio.gather(*tasks)

        total_ms = int((time.perf_counter() - document_started) * 1000)
        throughput = 0.0
        if total_ms > 0:
            throughput = (len(chunks) / total_ms) * 60_000
        final_limit = graph_sync_config.initial_concurrency
        if governor is not None:
            final_limit = governor.limit

        logger.info(
            "graph_sync_document_metrics %s",
            json.dumps(
                {
                    "event": "graph_sync_document_metrics",
                    "document_id": chunks[0].document_id,
                    "tenant_id": tenant_id,
                    "profile": graph_sync_config.profile,
                    "concurrency_mode": concurrency_mode,
                    "initial_concurrency": graph_sync_config.initial_concurrency,
                    "final_concurrency_limit": final_limit,
                    "total_chunks": len(chunks),
                    "total_ms": total_ms,
                    "chunks_per_minute": round(throughput, 3),
                    "llm_calls_total": total_llm_calls,
                    "tokens_total": total_tokens,
                    "cache_hits": cache_hits,
                    "chunk_errors": chunk_errors,
                },
                sort_keys=True,
            ),
        )

        # Log consolidated metrics
        try:
            from src.core.admin_ops.application.metrics.collector import MetricsCollector
            from src.shared.identifiers import generate_query_id

            if settings is None:
                raise RuntimeError("Settings not configured")

            collector = MetricsCollector(redis_url=settings.db.redis_url)

            label = f"Graph Extraction: {filename} ({len(chunks)} chunks)"
            async with collector.track_query(generate_query_id(), tenant_id, label) as qm:
                qm.operation = "extraction"
                qm.tokens_used = total_tokens
                qm.input_tokens = total_input_tokens
                qm.output_tokens = total_output_tokens
                qm.cost_estimate = total_cost
                qm.response = (
                    f"Extracted {total_entities} entities, {total_rels} relationships from "
                    f"{len(chunks)} chunks. LLM calls: {total_llm_calls}, cache hits: {cache_hits}."
                )
                qm.success = chunk_errors == 0

        except Exception as e:
            logger.error(f"Failed to log aggregated graph metrics: {e}")

        logger.info(f"Completed graph processing for {len(chunks)} chunks")


graph_processor = GraphProcessor()
