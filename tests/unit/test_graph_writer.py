from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.core.generation.application.prompts.entity_extraction import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)
from src.core.graph.application.writer import GraphWriter


def _build_result() -> ExtractionResult:
    return ExtractionResult(
        entities=[
            ExtractedEntity(name="A", type="CONCEPT", description="Entity A"),
            ExtractedEntity(name="B", type="CONCEPT", description="Entity B"),
        ],
        relationships=[
            ExtractedRelationship(
                source="A",
                target="B",
                type="RELATED_TO",
                description="A related to B",
                weight=0.9,
            ),
            ExtractedRelationship(
                source="B",
                target="A",
                type="DEPENDS_ON",
                description="B depends on A",
                weight=0.8,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_writer_uses_execute_write_batch_when_available():
    writer = GraphWriter()
    fake_graph_client = SimpleNamespace(
        execute_write=AsyncMock(),
        execute_write_batch=AsyncMock(),
    )

    with (
        patch(
            "src.core.graph.application.writer.get_graph_client",
            return_value=fake_graph_client,
        ),
        patch(
            "src.core.graph.application.communities.lifecycle.CommunityLifecycleManager"
        ) as mock_lifecycle_cls,
    ):
        lifecycle = AsyncMock()
        mock_lifecycle_cls.return_value = lifecycle

        await writer.write_extraction_result(
            document_id="doc1",
            chunk_id="chunk1",
            tenant_id="tenant1",
            result=_build_result(),
            filename="f.txt",
        )

    fake_graph_client.execute_write_batch.assert_awaited_once()
    fake_graph_client.execute_write.assert_not_called()
    lifecycle.mark_stale_by_entities_by_name.assert_awaited_once_with(["A", "B"], "tenant1")


@pytest.mark.asyncio
async def test_writer_falls_back_to_execute_write_without_batch_support():
    writer = GraphWriter()
    fake_graph_client = SimpleNamespace(
        execute_write=AsyncMock(),
    )

    with (
        patch(
            "src.core.graph.application.writer.get_graph_client",
            return_value=fake_graph_client,
        ),
        patch(
            "src.core.graph.application.communities.lifecycle.CommunityLifecycleManager"
        ) as mock_lifecycle_cls,
    ):
        lifecycle = AsyncMock()
        mock_lifecycle_cls.return_value = lifecycle

        await writer.write_extraction_result(
            document_id="doc1",
            chunk_id="chunk1",
            tenant_id="tenant1",
            result=_build_result(),
            filename="f.txt",
        )

    # 1 base query + 2 relationship-type queries
    assert fake_graph_client.execute_write.await_count == 3
    lifecycle.mark_stale_by_entities_by_name.assert_awaited_once_with(["A", "B"], "tenant1")
