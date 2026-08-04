"""
Regression tests for Issue #82: citation index in answer text can exceed the
returned sources array length.

GenerationService._map_sources cites/keeps only candidates the LLM actually
referenced, but the LLM numbers "[[Source: N]]" markers by position in the
*full* candidate list handed to it. Left untouched, a marker can name an
index past the end of the (shorter, cited-only) returned sources array. The
fix renumbers each marker to the source's final 1-based position in the
returned list, and strips markers that don't resolve to any candidate
(hallucinated or out-of-range indices) instead of leaving them dangling.
"""

import re

from src.core.generation.application.generation_service import GenerationService
from src.core.retrieval.domain.candidate import Candidate

CITATION_PATTERN = re.compile(r"\[\[Source:\s*(\d+)\]\]")


def _service() -> GenerationService:
    return object.__new__(GenerationService)


def _candidate(chunk_id: str, document_id: str) -> Candidate:
    return Candidate(chunk_id=chunk_id, content=f"content for {chunk_id}", document_id=document_id)


def test_map_sources_renumbers_markers_to_returned_position():
    svc = _service()
    candidates = [_candidate(f"c{i}", f"d{i}") for i in range(1, 6)]  # 5 candidates, only 2 cited
    answer = "Fact A [[Source: 2]]. Fact B [[Source: 4]]."

    rewritten, sources = svc._map_sources(answer, candidates)

    # Only the cited candidates come back, in ascending original order.
    assert [s.chunk_id for s in sources] == ["c2", "c4"]
    assert [s.index for s in sources] == [1, 2]

    # Markers in the text now match the returned array's positions, not the
    # original pre-filter candidate indices.
    assert "[[Source: 1]]" in rewritten
    assert "[[Source: 2]]" in rewritten
    cited_in_text = {int(m) for m in CITATION_PATTERN.findall(rewritten)}
    assert cited_in_text and max(cited_in_text) <= len(sources)


def test_map_sources_strips_hallucinated_out_of_range_marker():
    svc = _service()
    candidates = [_candidate("c1", "d1"), _candidate("c2", "d2")]
    answer = "Real fact [[Source: 1]]. Hallucinated fact [[Source: 5]]."

    rewritten, sources = svc._map_sources(answer, candidates)

    assert len(sources) == 1
    assert sources[0].chunk_id == "c1"
    assert "[[Source: 1]]" in rewritten
    # The unmappable marker is gone, not left dangling with an out-of-bounds index.
    assert "Source: 5" not in rewritten
    cited_in_text = {int(m) for m in CITATION_PATTERN.findall(rewritten)}
    assert max(cited_in_text, default=0) <= len(sources)


def test_map_sources_no_citations_is_noop():
    svc = _service()
    candidates = [_candidate("c1", "d1")]
    answer = "No citations here."

    rewritten, sources = svc._map_sources(answer, candidates)

    assert sources == []
    assert rewritten == answer
