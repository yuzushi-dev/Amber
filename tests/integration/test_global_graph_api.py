from unittest.mock import AsyncMock, patch

import pytest

from src.amber_platform.composition_root import platform
from src.api.routes.graph_editor import (
    get_node_neighborhood,
    get_top_nodes,
    search_nodes,
)


@pytest.mark.asyncio
async def test_get_top_nodes():
    """Test graph editor top-nodes endpoint handler."""
    mock_data = [
        {"id": "NodeA", "label": "NodeA", "type": "Entity", "community_id": 1, "degree": 10},
        {"id": "NodeB", "label": "NodeB", "type": "Entity", "community_id": 2, "degree": 5},
    ]

    with patch.object(platform.neo4j_client, "get_top_nodes", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_data
        result = await get_top_nodes(limit=5, tenant_id="test_tenant")

    assert len(result) == 2
    assert result[0].id == "NodeA"
    assert result[1].id == "NodeB"


@pytest.mark.asyncio
async def test_search_nodes():
    """Test graph editor search endpoint handler."""
    mock_data = [{"id": "Alpha", "label": "Alpha", "type": "Entity", "community_id": 1}]

    with patch.object(platform.neo4j_client, "search_nodes", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_data
        result = await search_nodes(q="Alp", limit=10, tenant_id="test_tenant")

    assert len(result) == 1
    assert result[0].id == "Alpha"


@pytest.mark.asyncio
async def test_get_neighborhood():
    """Test graph editor neighborhood endpoint handler."""
    mock_data = {
        "nodes": [
            {"id": "Center", "label": "Center", "type": "Node", "community_id": 1},
            {"id": "Neighbor", "label": "Neighbor", "type": "Node", "community_id": 1},
        ],
        "edges": [
            {"source": "Center", "target": "Neighbor", "type": "LINKS"},
        ],
    }

    with patch.object(
        platform.neo4j_client, "get_node_neighborhood_graph", new_callable=AsyncMock
    ) as mock_read:
        mock_read.return_value = mock_data
        result = await get_node_neighborhood(
            node_id="Center",
            limit=50,
            tenant_id="test_tenant",
        )

    assert len(result.nodes) == 2
    assert len(result.edges) == 1
