from unittest.mock import AsyncMock, patch

import pytest

from src.core.generation.application.prompts.entity_extraction import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)
from src.core.graph.application.writer import graph_writer
from src.core.graph.domain.ports.graph_client import set_graph_client


@pytest.mark.asyncio
async def test_graph_writer_pipeline_with_injected_graph_client():
    """
    Integration-style test for writer pipeline without external Neo4j.

    Validates that extraction payloads are translated into graph write calls
    and community staleness trigger is invoked.
    """
    tenant_id = "test_tenant_integration"
    doc_id = "doc_integration_1"
    chunk_id = "chunk_integration_1"

    extraction_result = ExtractionResult(
        entities=[
            ExtractedEntity(name="Neo4j", type="TECHNOLOGY", description="Graph Database"),
            ExtractedEntity(name="Python", type="TECHNOLOGY", description="Programming Language"),
        ],
        relationships=[
            ExtractedRelationship(
                source="Python",
                target="Neo4j",
                type="CONNECTS_TO",
                description="Python driver connects to Neo4j",
                weight=9,
            )
        ],
    )

    fake_graph_client = AsyncMock()
    fake_graph_client.execute_write = AsyncMock(return_value=[])
    fake_graph_client.execute_write_batch = AsyncMock(return_value=[])
    set_graph_client(fake_graph_client)

    with patch(
        "src.core.graph.application.communities.lifecycle.CommunityLifecycleManager"
    ) as mock_lifecycle_cls:
        lifecycle = AsyncMock()
        mock_lifecycle_cls.return_value = lifecycle

        await graph_writer.write_extraction_result(doc_id, chunk_id, tenant_id, extraction_result)

    fake_graph_client.execute_write_batch.assert_awaited_once()
    statements = fake_graph_client.execute_write_batch.await_args.args[0]
    assert len(statements) == 2  # base query + one relationship type query
    lifecycle.mark_stale_by_entities_by_name.assert_awaited_once_with(
        ["Neo4j", "Python"], tenant_id
    )
