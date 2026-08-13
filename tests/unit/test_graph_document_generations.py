from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.generation.application.prompts.entity_extraction import (
    ExtractedEntity,
    ExtractionResult,
)
from src.core.graph.application.processor import GraphProcessor
from src.core.graph.application.writer import GraphWriter
from src.core.graph.infrastructure.neo4j_client import Neo4jClient
from src.core.retrieval.application.search.graph import GraphSearcher
from src.core.retrieval.application.search.graph_traversal import GraphTraversalService


def _result() -> ExtractionResult:
    return ExtractionResult(
        entities=[ExtractedEntity(name="Amber", type="PRODUCT", description="A product")],
        relationships=[],
    )


@pytest.mark.asyncio
async def test_writer_scopes_chunk_identity_to_generation():
    writer = GraphWriter()
    graph = SimpleNamespace(execute_write=AsyncMock(), execute_write_batch=AsyncMock())

    with patch("src.core.graph.application.writer.get_graph_client", return_value=graph):
        await writer.write_extraction_result(
            document_id="doc-1",
            chunk_id="chunk-1",
            tenant_id="tenant-1",
            generation_id="gen-new",
            result=_result(),
        )

    query, params = graph.execute_write.await_args_list[0].args
    assert "generation_id: $generation_id" in query
    assert params["generation_id"] == "gen-new"


@pytest.mark.asyncio
async def test_processor_passes_generation_to_graph_writer():
    chunk = SimpleNamespace(
        id="chunk-1",
        document_id="doc-1",
        content="A sufficiently long chunk for the graph extraction pipeline to process.",
    )
    extractor = AsyncMock()
    extractor.extract.return_value = _result()

    with patch("src.core.graph.application.processor.graph_writer") as writer:
        writer.write_extraction_result = AsyncMock()
        processor = GraphProcessor(graph_extractor=extractor)
        await processor.process_chunks([chunk], "tenant-1", generation_id="gen-new")

    assert writer.write_extraction_result.await_args.kwargs["generation_id"] == "gen-new"


@pytest.mark.asyncio
async def test_cleanup_deletes_only_requested_document_generation():
    client = Neo4jClient(uri="bolt://unused", user="unused", password="unused")
    client.execute_write = AsyncMock(return_value=[{"deleted": 2}])

    deleted = await client.delete_document_generation("doc-1", "tenant-1", "gen-new")

    query, params = client.execute_write.await_args.args
    assert "c.generation_id = $generation_id" in query
    assert "DETACH DELETE c" in query
    assert params == {"document_id": "doc-1", "tenant_id": "tenant-1", "generation_id": "gen-new"}
    assert deleted == 2


@pytest.mark.asyncio
async def test_traversal_filters_staged_generations_and_keeps_legacy_chunks():
    graph = MagicMock(spec=Neo4jClient)
    graph.execute_read = AsyncMock(return_value=[])
    service = GraphTraversalService(graph)

    await service.beam_search(
        ["seed"],
        "tenant-1",
        active_generation_ids={"doc-1": "gen-live"},
    )

    query, params = graph.execute_read.await_args.args
    assert "c.is_published, false" in query
    assert (
        "c.generation_id IS NULL OR c.generation_id = $active_generation_ids[c.document_id]"
        in query
    )
    assert params["active_generation_ids"] == {"doc-1": "gen-live"}


def test_generation_relationships_are_staged_until_publish():
    relationship = SimpleNamespace(
        type="depends_on",
        model_dump=lambda: {"source": "A", "target": "B"},
    )

    statements = GraphWriter()._build_relationship_queries(
        relationships=[relationship],
        tenant_id="tenant-1",
        document_id="doc-1",
        generation_id="gen-new",
    )

    query, params = statements[0]
    assert "document_id: $document_id, generation_id: $generation_id" in query
    assert "r.is_staging = true" in query
    assert params["generation_id"] == "gen-new"


@pytest.mark.asyncio
async def test_graph_publish_promotes_only_requested_generation():
    client = Neo4jClient(uri="bolt://unused", user="unused", password="unused")
    client.execute_write = AsyncMock(return_value=[])

    await client.publish_document_generation("doc-1", "tenant-1", "gen-new")

    query, params = client.execute_write.await_args.args
    assert "c.is_published = true" in query
    assert "r.is_staging = false" in query
    assert params["generation_id"] == "gen-new"


@pytest.mark.asyncio
async def test_graph_search_hides_unpublished_chunks_but_keeps_legacy_chunks():
    graph = MagicMock(spec=Neo4jClient)
    graph.execute_read = AsyncMock(return_value=[])
    searcher = GraphSearcher(graph)

    await searcher.search_by_entities(["entity-1"], "tenant-1")
    entity_query, _ = graph.execute_read.await_args.args
    assert "coalesce(c.is_published, true) = true" in entity_query

    await searcher.search_by_neighbors(["chunk-1"], "tenant-1")
    neighbor_query, _ = graph.execute_read.await_args.args
    assert "coalesce(start.is_published, true) = true" in neighbor_query
    assert "coalesce(neighbor.is_published, true) = true" in neighbor_query


@pytest.mark.asyncio
async def test_graph_publish_hides_all_other_document_generations():
    client = Neo4jClient(uri="bolt://unused", user="unused", password="unused")
    client.execute_write = AsyncMock(return_value=[])

    await client.publish_document_generation("doc-1", "tenant-1", "gen-new")

    query, _ = client.execute_write.await_args.args
    assert "old.generation_id IS NULL OR old.generation_id <> $generation_id" in query
    assert "SET old.is_published = false" in query
    assert "old_rel.generation_id IS NOT NULL" in query
    assert "old_rel.generation_id <> $generation_id" in query
    assert "SET old_rel.is_staging = true" in query
