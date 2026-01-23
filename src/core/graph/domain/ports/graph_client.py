from typing import Any, Protocol


class GraphClientPort(Protocol):
    async def execute_read(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ...

    async def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ...


_graph_client: GraphClientPort | None = None


def set_graph_client(client: GraphClientPort | None) -> None:
    global _graph_client
    _graph_client = client


def get_graph_client() -> GraphClientPort:
    if _graph_client is None:
        raise RuntimeError("Graph client not configured. Call set_graph_client() at startup.")
    return _graph_client
