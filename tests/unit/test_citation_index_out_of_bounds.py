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


def test_map_sources_expands_comma_grouped_citation_marker():
    """Regression test for Issue #103.

    The LLM sometimes groups several citations in one bracket, e.g.
    "[[Source: 2, 4]]" instead of two separate "[[Source: 2]] [[Source: 4]]"
    markers. The single-index regex used to detect and renumber citations
    doesn't match that comma-separated form at all, so those indices were
    silently dropped: never renumbered, never contributing to the returned
    `sources` list, and left dangling in the answer text with their original
    (pre-filter) indices.
    """
    svc = _service()
    candidates = [_candidate(f"c{i}", f"d{i}") for i in range(1, 6)]  # 5 candidates
    answer = "Fact A [[Source: 2, 4]]. Fact B [[Source: 1]]."

    rewritten, sources = svc._map_sources(answer, candidates)

    # All three cited candidates (1, 2, 4) come back, in ascending original order.
    assert [s.chunk_id for s in sources] == ["c1", "c2", "c4"]

    # The grouped marker is split and each half renumbered to the returned
    # array's position -- no marker names an index past len(sources).
    cited_in_text = {int(m) for m in CITATION_PATTERN.findall(rewritten)}
    assert cited_in_text and max(cited_in_text) <= len(sources)
    assert "Source: 2, 4" not in rewritten
    assert "Source: 2," not in rewritten


def test_map_sources_grouped_citation_strips_hallucinated_index():
    """A comma-grouped marker mixing a valid and an out-of-range index must
    keep the valid one and drop the hallucinated one, not leave it dangling."""
    svc = _service()
    candidates = [_candidate("c1", "d1"), _candidate("c2", "d2")]
    answer = "Fact A [[Source: 1, 9]]."

    rewritten, sources = svc._map_sources(answer, candidates)

    assert [s.chunk_id for s in sources] == ["c1"]
    assert "[[Source: 1]]" in rewritten
    assert "Source: 9" not in rewritten


def test_map_sources_grouped_citation_requires_source_keyword_or_double_bracket():
    """A bare single-bracket comma list (e.g. numpy/pandas fancy indexing in
    a code sample, "arr[0, 1]") must NOT be treated as a citation group."""
    svc = _service()
    candidates = [_candidate("c1", "d1"), _candidate("c2", "d2")]
    answer = "Use `arr[0, 1]` to select those elements. [[Source: 1]]"

    rewritten, sources = svc._map_sources(answer, candidates)

    assert [s.chunk_id for s in sources] == ["c1"]
    assert "arr[0, 1]" in rewritten


def test_map_sources_preserves_literal_whitespace_and_punctuation_when_renumbering():
    svc = _service()
    candidates = [_candidate("c1", "d1"), _candidate("c2", "d2")]
    code = '```js\n  const label = m(`label.view_mail`, `VIEW MAIL`);\n  const value = "x   !";\n```'
    inline_literal = "`x  !`"
    answer = f"{code}\nInline {inline_literal} [[Source: 2]]."

    rewritten, sources = svc._map_sources(answer, candidates)

    assert [source.chunk_id for source in sources] == ["c2"]
    assert code in rewritten
    assert inline_literal in rewritten
    assert rewritten.endswith("[[Source: 1]].")


def test_code_markers_do_not_normalize_collect_or_renumber():
    svc = _service()
    candidates = [_candidate("c1", "d1"), _candidate("c2", "d2")]
    code = (
        "``arr[1]`` `arr[\n  1] and [[Source: 2]]` ```code [[Source: 1]]```\n~~~py\n[1]\n~~~~\n"
        "    [[Source: 1]]\n\t[[Source: 1]]\n> ~~~\n> [[Source: 1]]\n> ~~~~\n"
    )
    answer = f"{code}- quoted list [[Source: 2]]\n    list continuation [[Source: 2]]\n> - nested `[[Source: 1]]\n>   still [[Source: 1]]` [[Source: 2]]\n> prose [[Source: 2]]\nUse [[Source: 2]]."

    rewritten, sources = svc._map_sources(answer, candidates)

    assert [source.chunk_id for source in sources] == ["c2"]
    assert rewritten.startswith(code)
    assert rewritten.endswith("- quoted list [[Source: 1]]\n    list continuation [[Source: 1]]\n> - nested `[[Source: 1]]\n>   still [[Source: 1]]` [[Source: 1]]\n> prose [[Source: 1]]\nUse [[Source: 1]].")


def test_code_only_and_escaped_markers_do_not_add_sources():
    svc = _service()
    candidates = [_candidate("c1", "d1")]

    rewritten, sources = svc._map_sources("`arr[1]` and \\[1]", candidates)

    assert sources == []
    assert rewritten == "`arr[1]` and \\[1]"

    rewritten, sources = svc._map_sources("~~~\n[[Source: 1]]\n[[Source: 1]]", candidates)

    assert sources == []
    assert rewritten == "~~~\n[[Source: 1]]\n[[Source: 1]]"


def test_repeated_lines_and_crlf_map_to_original_code_ranges():
    svc = _service()
    candidates = [_candidate("c1", "d1")]
    answer = "`[[Source: 1]]`\r\n`[[Source: 1]]`\r\n```\r\n[[Source: 1]]\r\n```\r\nUse [[Source: 1]]."

    rewritten, sources = svc._map_sources(answer, candidates)

    assert [source.chunk_id for source in sources] == ["c1"]
    assert rewritten == "`[[Source: 1]]`\r\n`[[Source: 1]]`\r\n```\r\n[[Source: 1]]\r\n```\r\nUse [[Source: 1]]."


def test_html_code_and_pre_tags_are_protected_without_rewriting_prose():
    svc = _service()
    candidates = [_candidate("c1", "d1"), _candidate("c2", "d2")]
    answer = (
        "Prose [[Source: 2]]; <code class='literal'>[1]</code>; "
        "<pre data-kind='raw'>\n\n[[Source: 1]]\n</pre>"
    )

    rewritten, sources = svc._map_sources(answer, candidates)

    assert [source.chunk_id for source in sources] == ["c2"]
    assert rewritten == (
        "Prose [[Source: 1]]; <code class='literal'>[1]</code>; "
        "<pre data-kind='raw'>\n\n[[Source: 1]]\n</pre>"
    )


def test_html_unclosed_and_markdown_fence_boundaries_are_conservative():
    svc = _service()
    candidates = [_candidate("c1", "d1")]
    unclosed = "<code data-x='y'>[1]\n[[Source: 1]]"
    fenced = "~~~\n<code>literal\n~~~\rprose [[Source: 1]]"

    rewritten_unclosed, sources_unclosed = svc._map_sources(unclosed, candidates)
    rewritten_fenced, sources_fenced = svc._map_sources(fenced, candidates)

    assert sources_unclosed == []
    assert rewritten_unclosed == unclosed
    assert [source.chunk_id for source in sources_fenced] == ["c1"]
    assert rewritten_fenced == "~~~\n<code>literal\n~~~\rprose [[Source: 1]]"


def test_escaped_html_opening_does_not_protect_following_prose():
    svc = _service()
    candidates = [_candidate("c1", "d1")]

    rewritten, sources = svc._map_sources("\\<code>[1] prose [[Source: 1]]", candidates)

    assert [source.chunk_id for source in sources] == ["c1"]
    assert rewritten == "\\<code>[[Source: 1]] prose [[Source: 1]]"


def test_html_tag_literal_inside_markdown_code_does_not_protect_later_prose():
    svc = _service()
    candidates = [_candidate("c1", "d1"), _candidate("c2", "d2")]
    answer = "Use `<code>` then [[Source: 2]]"

    rewritten, sources = svc._map_sources(answer, candidates)

    assert [source.chunk_id for source in sources] == ["c2"]
    assert rewritten == "Use `<code>` then [[Source: 1]]"
