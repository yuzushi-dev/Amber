from src.core.models.candidate import Candidate
from src.core.retrieval.fusion import fuse_results


def test_rrf_fusion_basic():
    """Verify basic RRF ranking logic."""
    group_a = [
        Candidate(chunk_id="1", content="A", score=0.9, source="vector"),
        Candidate(chunk_id="2", content="B", score=0.8, source="vector"),
    ]
    group_b = [
        Candidate(chunk_id="2", content="B", score=0.7, source="graph"),
        Candidate(chunk_id="3", content="C", score=0.6, source="graph"),
    ]

    results = fuse_results({"vector": group_a, "graph": group_b}, k=1)

    # Candidate 2 is in both lists at ranks 2 and 1
    # Score for 2: 1/(1+2) + 1/(1+1) = 0.33 + 0.5 = 0.83
    # Score for 1: 1/(1+1) = 0.5
    # Score for 3: 1/(1+2) = 0.33

    assert results[0].chunk_id == "2"
    assert results[0].source == "hybrid"
    assert results[1].chunk_id == "1"
    assert results[2].chunk_id == "3"

def test_rrf_fusion_weights():
    """Verify RRF respects source weights."""
    group_a = [Candidate(chunk_id="vec", content="V", score=1.0, source="vector")]
    group_b = [Candidate(chunk_id="graph", content="G", score=1.0, source="graph")]

    # Boost graph
    results = fuse_results(
        {"vector": group_a, "graph": group_b},
        k=1,
        weights={"vector": 1.0, "graph": 2.0}
    )

    assert results[0].chunk_id == "graph"
