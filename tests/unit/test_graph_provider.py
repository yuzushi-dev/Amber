import pytest

from src.core.tools.graph import query_graph
from src.core.graph.domain.ports.graph_client import set_graph_client


class FakeGraphClient:
    async def execute_read(self, query, parameters=None):
        return [{"id": "1"}, {"id": "2"}]


@pytest.mark.asyncio
async def test_query_graph_uses_injected_client():
    set_graph_client(FakeGraphClient())
    result = await query_graph("MATCH (n) RETURN n")
    assert "{'id': '1'}" in result


@pytest.mark.asyncio
async def test_query_graph_raises_when_not_configured():
    set_graph_client(None)
    result = await query_graph("MATCH (n) RETURN n")
    assert "Graph client not configured" in result
