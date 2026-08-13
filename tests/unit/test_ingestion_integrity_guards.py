from types import SimpleNamespace

import pytest

from src.core.graph.application import processor as processor_module
from src.core.ingestion.application.ingestion_service import IngestionService


def _chunks(count: int):
    return [
        SimpleNamespace(
            id=f"chunk-{index}",
            document_id="doc-1",
            content=f"content-{index}",
            metadata_={},
        )
        for index in range(count)
    ]


def test_milvus_payload_rejects_dense_cardinality_drift():
    with pytest.raises(ValueError, match="Dense embedding cardinality mismatch"):
        IngestionService._build_milvus_data(_chunks(2), [[0.1]], [{}, {}], "tenant-1", "gen-1")


def test_milvus_payload_keeps_generation_identity():
    payload = IngestionService._build_milvus_data(_chunks(1), [[0.1]], [{}], "tenant-1", "gen-1")

    assert payload[0]["generation_id"] == "gen-1"


def test_partial_graph_result_fails_the_staging_generation():
    assert hasattr(processor_module, "GraphProcessingResult")
    result = processor_module.GraphProcessingResult(total_chunks=2, failed_chunk_ids=["chunk-1"])

    with pytest.raises(RuntimeError, match="1 of 2 chunks"):
        result.raise_if_partial()
