import pytest

from src.core.graph.domain.ports.graph_client import set_graph_client
from src.core.tools.graph import create_graph_tool


class FakeGraphClient:
    async def execute_read(self, query, parameters=None):
        return [{"id": "1"}, {"id": "2"}]


def _tool(tenant_id: str = "tenant-1"):
    """Return the bound query_graph callable from the tenant-scoped factory."""
    return create_graph_tool(tenant_id)["func"]


@pytest.mark.asyncio
async def test_query_graph_uses_injected_client():
    set_graph_client(FakeGraphClient())
    query_graph = _tool()
    result = await query_graph("MATCH (n) WHERE n.tenant_id = $tenant_id RETURN n")
    assert "{'id': '1'}" in result


@pytest.mark.asyncio
async def test_query_graph_raises_when_not_configured():
    set_graph_client(None)
    query_graph = _tool()
    result = await query_graph("MATCH (n) WHERE n.tenant_id = $tenant_id RETURN n")
    assert "Graph client not configured" in result


@pytest.mark.asyncio
async def test_query_graph_rejects_write_clauses():
    set_graph_client(FakeGraphClient())
    query_graph = _tool()
    result = await query_graph("MATCH (n) WHERE n.tenant_id = $tenant_id DETACH DELETE n")
    assert "not permitted" in result
