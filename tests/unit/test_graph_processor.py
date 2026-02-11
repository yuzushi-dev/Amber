import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.core.generation.application.prompts.entity_extraction import (
    ExtractedEntity,
    ExtractionResult,
    ExtractionUsage,
)
from src.core.graph.application.processor import GraphProcessor


def _chunk(chunk_id: str, document_id: str, content: str):
    return SimpleNamespace(id=chunk_id, document_id=document_id, content=content)


@pytest.mark.asyncio
async def test_processor_flow():
    with patch("src.core.graph.application.processor.graph_writer") as mock_writer:
        mock_extractor = AsyncMock()
        ExtractionResult(entities=[], relationships=[])
        mock_result_with_entities = ExtractionResult(
            entities=[{"name": "E1", "type": "T", "description": "D"}], relationships=[]
        )
        mock_extractor.extract = AsyncMock(return_value=mock_result_with_entities)

        mock_writer.write_extraction_result = AsyncMock()

        chunks = [
            _chunk(
                "c1",
                "d1",
                "Text 1 is long enough to be processed by the graph processor logic.",
            ),
            _chunk(
                "c2",
                "d1",
                "Text 2 is also long enough to be processed by the graph processor logic.",
            ),
        ]

        processor = GraphProcessor(graph_extractor=mock_extractor)

        await processor.process_chunks(chunks, "tenant_1")

        assert mock_extractor.extract.call_count == 2
        assert mock_writer.write_extraction_result.call_count == 2


@pytest.mark.asyncio
async def test_write_happens_outside_llm_semaphore():
    extract_start: dict[str, float] = {}
    write_window: dict[str, tuple[float, float]] = {}

    async def _extract(text, chunk_id=None, **kwargs):
        extract_start[chunk_id] = time.perf_counter()
        await asyncio.sleep(0.01)
        return ExtractionResult(
            entities=[ExtractedEntity(name="E1", type="CONCEPT", description="D1")],
            relationships=[],
            usage=ExtractionUsage(total_tokens=1, llm_calls=1),
        )

    async def _write(document_id, chunk_id, tenant_id, result, filename=None):
        start = time.perf_counter()
        await asyncio.sleep(0.08 if chunk_id == "c1" else 0.01)
        write_window[chunk_id] = (start, time.perf_counter())

    chunks = [
        _chunk("c1", "d1", "Chunk 1 is long enough to be processed by graph pipeline code path."),
        _chunk("c2", "d1", "Chunk 2 is long enough to be processed by graph pipeline code path."),
    ]

    mock_extractor = AsyncMock()
    mock_extractor.extract = AsyncMock(side_effect=_extract)

    with (
        patch("src.core.graph.application.processor.graph_writer") as mock_writer,
        patch(
            "src.core.graph.application.processor.resolve_graph_sync_runtime_config"
        ) as mock_resolve,
    ):
        mock_writer.write_extraction_result = AsyncMock(side_effect=_write)
        mock_resolve.return_value.initial_concurrency = 1
        mock_resolve.return_value.max_concurrency = 2
        mock_resolve.return_value.adaptive_concurrency_enabled = False
        mock_resolve.return_value.profile = "local_weak"

        processor = GraphProcessor(graph_extractor=mock_extractor)
        await processor.process_chunks(chunks, "tenant_1")

    assert "c1" in write_window
    assert "c2" in extract_start
    c1_write_end = write_window["c1"][1]
    c2_extract_start = extract_start["c2"]
    assert c2_extract_start < c1_write_end


@pytest.mark.asyncio
async def test_processor_emits_chunk_and_document_metrics(caplog):
    caplog.set_level(logging.INFO)

    mock_result = ExtractionResult(
        entities=[ExtractedEntity(name="E1", type="CONCEPT", description="D1")],
        relationships=[],
        usage=ExtractionUsage(total_tokens=42, input_tokens=20, output_tokens=22, llm_calls=1),
    )

    chunk = _chunk(
        "c1",
        "d1",
        "A sufficiently long chunk to trigger extraction and metrics logging behavior.",
    )

    with patch("src.core.graph.application.processor.graph_writer") as mock_writer:
        mock_writer.write_extraction_result = AsyncMock()
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=mock_result)

        processor = GraphProcessor(graph_extractor=mock_extractor)
        await processor.process_chunks([chunk], "tenant_1")

    messages = [record.getMessage() for record in caplog.records]
    assert any("graph_sync_chunk_metrics" in m for m in messages)
    assert any("graph_sync_document_metrics" in m for m in messages)


@pytest.mark.asyncio
async def test_processor_passes_chunk_progress_to_extractor():
    mock_result = ExtractionResult(
        entities=[ExtractedEntity(name="E1", type="CONCEPT", description="D1")],
        relationships=[],
        usage=ExtractionUsage(total_tokens=1, llm_calls=1),
    )

    chunks = [
        _chunk("c1", "d1", "Chunk 1 is long enough to be processed by graph pipeline code path."),
        _chunk("c2", "d1", "Chunk 2 is long enough to be processed by graph pipeline code path."),
    ]

    with patch("src.core.graph.application.processor.graph_writer") as mock_writer:
        mock_writer.write_extraction_result = AsyncMock()
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=mock_result)

        processor = GraphProcessor(graph_extractor=mock_extractor)
        await processor.process_chunks(chunks, "tenant_1")

    observed = {
        (
            call.kwargs["chunk_id"],
            call.kwargs["chunk_number"],
            call.kwargs["total_chunks"],
        )
        for call in mock_extractor.extract.await_args_list
    }
    assert observed == {("c1", 1, 2), ("c2", 2, 2)}


@pytest.mark.asyncio
async def test_processor_supports_adaptive_concurrency_mode(caplog):
    caplog.set_level(logging.INFO)

    mock_result = ExtractionResult(
        entities=[ExtractedEntity(name="E1", type="CONCEPT", description="D1")],
        relationships=[],
        usage=ExtractionUsage(total_tokens=1, llm_calls=1),
    )

    chunk = _chunk(
        "c1",
        "d1",
        "A sufficiently long chunk to trigger adaptive concurrency mode execution path.",
    )

    with (
        patch("src.core.graph.application.processor.graph_writer") as mock_writer,
        patch(
            "src.core.graph.application.processor.resolve_graph_sync_runtime_config"
        ) as mock_resolve,
    ):
        mock_writer.write_extraction_result = AsyncMock()
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=mock_result)

        mock_resolve.return_value.profile = "adaptive"
        mock_resolve.return_value.initial_concurrency = 1
        mock_resolve.return_value.max_concurrency = 2
        mock_resolve.return_value.adaptive_concurrency_enabled = True

        processor = GraphProcessor(graph_extractor=mock_extractor)
        await processor.process_chunks([chunk], "tenant_1")

    messages = [record.getMessage() for record in caplog.records]
    assert any('"concurrency_mode": "adaptive"' in m for m in messages)
