from typing import Any, Protocol


class GraphExtractorPort(Protocol):
    """Port for extracting graph entities/relationships from text."""

    async def extract(self, text: str, chunk_id: str = "UNKNOWN") -> Any:
        ...


_graph_extractor: GraphExtractorPort | None = None


def set_graph_extractor(extractor: GraphExtractorPort | None) -> None:
    global _graph_extractor
    _graph_extractor = extractor


def get_graph_extractor() -> GraphExtractorPort:
    if _graph_extractor is None:
        raise RuntimeError("Graph extractor not configured. Call set_graph_extractor() at startup.")
    return _graph_extractor
