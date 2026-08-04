"""Regression test for the "Untitled" sources bug.

_get_document_titles() must read document_id from the top-level Candidate
field, not from Candidate.metadata (where vector search never puts it). When
it read the wrong place, doc_ids came out empty, get_titles_by_ids() was
never asked for the real ids, and every source rendered as "Untitled" even
though the document_id itself was correct.
"""

import asyncio

from src.core.generation.application.generation_service import GenerationService
from src.core.retrieval.domain.candidate import Candidate


class _FakeDocRepo:
    def __init__(self, titles):
        self._titles = titles
        self.asked_for = None

    async def get_titles_by_ids(self, document_ids):
        self.asked_for = list(document_ids)
        return {d: self._titles[d] for d in document_ids if d in self._titles}


def _service_with(repo):
    svc = object.__new__(GenerationService)  # bypass heavy __init__
    svc.document_repository = repo
    return svc


def test_titles_resolved_from_top_level_document_id():
    repo = _FakeDocRepo({"doc_abc": "Carbonio_2FA.html"})
    svc = _service_with(repo)
    # Mirrors real retrieval: document_id top-level, metadata holds only content.
    cand = Candidate(chunk_id="c1", content="...", document_id="doc_abc",
                     metadata={"content": "..."})

    titles = asyncio.run(svc._get_document_titles([cand]))

    assert repo.asked_for == ["doc_abc"], "document_id must reach the title lookup"
    assert titles == {"doc_abc": "Carbonio_2FA.html"}


def test_dict_candidate_still_works():
    repo = _FakeDocRepo({"doc_xyz": "Quota.html"})
    svc = _service_with(repo)
    titles = asyncio.run(svc._get_document_titles([{"document_id": "doc_xyz"}]))
    assert titles == {"doc_xyz": "Quota.html"}


def test_map_sources_uses_db_titles_not_untitled():
    """_map_sources must title cited sources from the DB doc_titles map.

    Vector-search candidates carry no document_title in metadata, so relying on
    metadata alone rendered every cited source as "Untitled" (the visible bug).
    """
    svc = _service_with(_FakeDocRepo({}))
    cand = Candidate(chunk_id="c1", content="body", document_id="doc_abc",
                     metadata={"content": "body"})  # no document_title here

    # Without the DB map -> falls back to Untitled (old behaviour)
    _rewritten_no_map, src_no_map = svc._map_sources("see [[Source: 1]]", [cand])
    assert src_no_map[0].title == "Untitled"

    # With the DB map -> real filename
    _rewritten_with_map, src_with_map = svc._map_sources(
        "see [[Source: 1]]", [cand], {"doc_abc": "Carbonio_2FA.html"}
    )
    assert src_with_map[0].title == "Carbonio_2FA.html"


if __name__ == "__main__":
    test_titles_resolved_from_top_level_document_id()
    test_dict_candidate_still_works()
    test_map_sources_uses_db_titles_not_untitled()
    print("ok")
