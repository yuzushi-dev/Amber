from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.retrieval.application import retrieval_service as rs
from src.core.retrieval.application.query.router import SearchMode
from src.core.retrieval.application.retrieval_service import RetrievalService
from src.shared.kernel.models.query import QueryOptions


def _chunk(chunk_id, document_id, score=1.0):
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "content": chunk_id,
        "score": score,
        "score_type": "reranker",
        "source": "vector",
    }


def _row(chunk_id, document_id):
    return SimpleNamespace(
        id=chunk_id,
        document_id=document_id,
        content=chunk_id + " text",
        metadata_={"document_title": document_id},
    )


def _service(following):
    service = RetrievalService.__new__(RetrievalService)
    service.document_repository = SimpleNamespace(get_next_chunks=AsyncMock(return_value=following))
    return service


@pytest.mark.asyncio
async def test_run_end_gets_its_continuation_right_after_it():
    chunks = [_chunk("a1", "a", 0.9), _chunk("b1", "b", 0.8), _chunk("a2", "a", 0.7)]
    service = _service({"a1": _row("a2", "a"), "a2": _row("a3", "a")})
    trace = []

    out = await service._append_document_continuations(chunks, allowed_ids={"a", "b"}, trace=trace)

    assert [c["chunk_id"] for c in out] == ["a1", "b1", "a2", "a3"]
    added = out[3]
    assert added["document_id"] == "a" and added["content"] == "a3 text"
    assert added["score"] == 0.7 and added["source"] == "document_continuation"
    assert added["metadata"] == {"document_title": "a"}
    # single-chunk documents are never looked up
    service.document_repository.get_next_chunks.assert_awaited_once_with(["a1", "a2"])
    assert trace == [
        {
            "step": "document_continuations",
            "added": [{"chunk_id": "a3", "after": "a2", "gap_hit": False}],
        }
    ]


@pytest.mark.asyncio
async def test_single_chunk_documents_are_left_alone():
    chunks = [_chunk("a1", "a"), _chunk("b1", "b")]
    service = _service({})

    assert await service._append_document_continuations(chunks, allowed_ids={"a", "b"}) == chunks
    service.document_repository.get_next_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_cap_keeps_higher_ranked_parents_first(monkeypatch):
    monkeypatch.setattr(rs, "MAX_DOCUMENT_CONTINUATIONS", 1)
    chunks = [_chunk("a1", "a"), _chunk("b1", "b"), _chunk("a5", "a"), _chunk("b7", "b")]
    service = _service({"a1": _row("a2", "a"), "b1": _row("b2", "b"), "a5": _row("a6", "a")})

    out = await service._append_document_continuations(chunks, allowed_ids={"a", "b"})

    assert [c["chunk_id"] for c in out] == ["a1", "a2", "b1", "a5", "b7"]


@pytest.mark.asyncio
async def test_foreign_or_disallowed_rows_are_dropped():
    chunks = [_chunk("a1", "a"), _chunk("a4", "a"), _chunk("c1", "c"), _chunk("c3", "c")]
    service = _service(
        {
            "a1": _row("x9", "x"),  # not the parent's document
            "a4": _row("a5", "a"),  # fine
            "c1": _row("c2", "c"),  # document outside the caller's visible set
        }
    )

    out = await service._append_document_continuations(chunks, allowed_ids={"a", "x"})

    assert [c["chunk_id"] for c in out] == ["a1", "a4", "a5", "c1", "c3"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repository",
    [
        object(),
        SimpleNamespace(get_next_chunks=AsyncMock(side_effect=RuntimeError("db down"))),
        SimpleNamespace(get_next_chunks=MagicMock(return_value="not awaitable")),
        SimpleNamespace(get_next_chunks=AsyncMock(return_value=["not", "a", "dict"])),
    ],
)
async def test_lookup_problems_leave_context_unchanged(repository):
    chunks = [_chunk("a1", "a"), _chunk("a2", "a")]
    service = RetrievalService.__new__(RetrievalService)
    service.document_repository = repository

    assert await service._append_document_continuations(chunks, allowed_ids={"a"}) == chunks


@pytest.mark.asyncio
async def test_generation_retrieval_appends_continuation_after_scope_filter():
    service = RetrievalService.__new__(RetrievalService)
    service.config = SimpleNamespace(top_k=5)
    service._get_effective_tenant_config = AsyncMock(return_value={})
    service._list_visible_document_ids = AsyncMock(return_value=["a", "b"])
    service.document_repository = SimpleNamespace(
        get_editions_by_ids=AsyncMock(return_value={"a": "commercial", "b": "commercial"}),
        list_visible_document_ids_by_taxonomy=AsyncMock(return_value=[]),
        get_next_chunks=AsyncMock(return_value={"a2": _row("a3", "a")}),
    )
    scopes = SimpleNamespace(
        effective_tenant_id="tenant",
        vector_scopes=["tenant"],
        graph_scopes=["tenant"],
        group_ids=[],
        enforce_groups=True,
    )
    service.router = SimpleNamespace(route=AsyncMock(return_value=SearchMode.BASIC))
    service._resolve_vector_targets = AsyncMock(return_value=[])
    service._execute_vector_search = AsyncMock(
        return_value=SimpleNamespace(
            chunks=[
                _chunk("a1", "a"),
                _chunk("a2", "a"),
                _chunk("b1", "b"),
                _chunk("z1", "z"),
            ],
            trace=[],
        )
    )
    service.circuit_breaker = MagicMock()

    result = await service.retrieve(
        "question",
        "tenant",
        document_ids=["a", "b"],
        options=QueryOptions(use_sufficiency_loop=False),
        query_scopes=scopes,
        for_generation=True,
    )

    assert [c["chunk_id"] for c in result.chunks] == ["a1", "a2", "a3", "b1"]
    service.document_repository.get_next_chunks.assert_awaited_once_with(["a1", "a2"])


class _Savepoint:
    def __init__(self):
        self.exits = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exits.append(exc_type)
        return False


def _repository(execute):
    savepoint = _Savepoint()
    repository = PostgresDocumentRepository.__new__(PostgresDocumentRepository)
    repository._session = SimpleNamespace(execute=execute, begin_nested=lambda: savepoint)
    return repository, savepoint


@pytest.mark.asyncio
async def test_repository_next_chunk_query_is_scoped_to_same_published_generation():
    execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [("a1", "row")]))
    repository, savepoint = _repository(execute)

    assert await repository.get_next_chunks(["a1"]) == {"a1": "row"}
    assert await repository.get_next_chunks([]) == {}
    assert savepoint.exits == [None]

    sql = " ".join(
        str(
            execute.await_args.args[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )
    for fragment in (
        "chunks.tenant_id = chunks_1.tenant_id",
        "chunks.document_id = chunks_1.document_id",
        "chunks.generation_id IS NOT DISTINCT FROM chunks_1.generation_id",
        "chunks.index = chunks_1.index + 1 ",
        "WHERE chunks_1.id IN ('a1')",
        "documents.active_generation_id IS NULL AND chunks.generation_id IS NULL",
        "OR chunks.generation_id = documents.active_generation_id",
        "ORDER BY chunks_1.id, chunks.id",
    ):
        assert fragment in sql, fragment
    execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_repository_failure_unwinds_through_savepoint():
    repository, savepoint = _repository(AsyncMock(side_effect=RuntimeError("statement timeout")))

    with pytest.raises(RuntimeError):
        await repository.get_next_chunks(["a1"])
    assert savepoint.exits == [RuntimeError]


@pytest.mark.asyncio
async def test_gap_hit_gets_continuation_even_as_single_document_chunk():
    gap_hit = {**_chunk("g11", "g"), "sufficiency_gap_hit": True}
    chunks = [_chunk("a1", "a"), gap_hit]
    service = _service({"g11": _row("g12", "g")})

    out = await service._append_document_continuations(chunks, allowed_ids={"a", "g"})

    assert [c["chunk_id"] for c in out] == ["a1", "g11", "g12"]
    assert "sufficiency_gap_hit" not in out[2]  # continuations never chain
    service.document_repository.get_next_chunks.assert_awaited_once_with(["g11"])


@pytest.mark.asyncio
async def test_gap_and_document_continuations_have_separate_caps(monkeypatch):
    monkeypatch.setattr(rs, "MAX_DOCUMENT_CONTINUATIONS", 1)
    monkeypatch.setattr(rs, "MAX_GAP_CONTINUATIONS", 1)
    chunks = [
        _chunk("a1", "a"),
        _chunk("a5", "a"),
        _chunk("b1", "b"),
        _chunk("b5", "b"),
        {**_chunk("g1", "g"), "sufficiency_gap_hit": True},
        {**_chunk("h1", "h"), "sufficiency_gap_hit": True},
    ]
    service = _service(
        {
            "a1": _row("a2", "a"),
            "b1": _row("b2", "b"),
            "g1": _row("g2", "g"),
            "h1": _row("h2", "h"),
        }
    )

    out = await service._append_document_continuations(chunks, allowed_ids={"a", "b", "g", "h"})

    # exhausting the document cap (a2) must not block the first gap continuation (g2)
    assert [c["chunk_id"] for c in out] == ["a1", "a2", "a5", "b1", "b5", "g1", "g2", "h1"]


def _head_service(heads, following=None):
    service = _service(following or {})
    service.document_repository.get_first_chunks = AsyncMock(return_value=heads)
    return service


@pytest.mark.asyncio
async def test_head_is_inserted_before_first_chunk_of_multi_chunk_document():
    chunks = [_chunk("b1", "b"), _chunk("a7", "a"), _chunk("a8", "a")]
    service = _head_service({"a": _row("a0", "a")})
    trace = []

    out = await service._append_document_continuations(chunks, allowed_ids={"a", "b"}, trace=trace)

    assert [c["chunk_id"] for c in out] == ["b1", "a0", "a7", "a8"]
    assert out[1]["source"] == "document_head"
    service.document_repository.get_first_chunks.assert_awaited_once_with(["a"])
    assert trace == [{"step": "document_heads", "added": [{"chunk_id": "a0", "before": "a7"}]}]


@pytest.mark.asyncio
async def test_no_head_when_document_contributes_one_chunk():
    service = _head_service({"a": _row("a0", "a")})

    out = await service._append_document_continuations([_chunk("a7", "a")], allowed_ids={"a"})

    assert [c["chunk_id"] for c in out] == ["a7"]
    service.document_repository.get_first_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_no_duplicate_head_when_already_selected():
    chunks = [_chunk("a7", "a"), _chunk("a0", "a")]
    service = _head_service({"a": _row("a0", "a")})

    out = await service._append_document_continuations(chunks, allowed_ids={"a"})

    assert [c["chunk_id"] for c in out] == ["a7", "a0"]


@pytest.mark.asyncio
async def test_head_skipped_for_document_outside_allowed_ids():
    chunks = [_chunk("a7", "a"), _chunk("a8", "a")]
    service = _head_service({"a": _row("a0", "a")})

    out = await service._append_document_continuations(chunks, allowed_ids={"b"})

    assert out == chunks
    service.document_repository.get_first_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_head_cap_limits_documents(monkeypatch):
    monkeypatch.setattr(rs, "MAX_DOCUMENT_HEADS", 1)
    chunks = [_chunk("a7", "a"), _chunk("b7", "b"), _chunk("a8", "a"), _chunk("b8", "b")]
    service = _head_service({"a": _row("a0", "a"), "b": _row("b0", "b")})

    out = await service._append_document_continuations(chunks, allowed_ids={"a", "b"})

    assert [c["chunk_id"] for c in out] == ["a0", "a7", "b7", "a8", "b8"]
    service.document_repository.get_first_chunks.assert_awaited_once_with(["a"])


@pytest.mark.asyncio
async def test_head_lookup_failure_leaves_context_unchanged():
    chunks = [_chunk("a7", "a"), _chunk("a8", "a")]
    service = _service({})
    service.document_repository.get_first_chunks = AsyncMock(side_effect=RuntimeError("db down"))

    assert await service._append_document_continuations(chunks, allowed_ids={"a"}) == chunks


@pytest.mark.asyncio
async def test_repository_first_chunk_query_is_scoped_to_published_generation():
    execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [("a", "row")]))
    repository, savepoint = _repository(execute)

    assert await repository.get_first_chunks(["a"]) == {"a": "row"}
    assert await repository.get_first_chunks([]) == {}
    assert savepoint.exits == [None]

    sql = " ".join(
        str(
            execute.await_args.args[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )
    assert "DISTINCT ON (chunks.document_id)" in sql
    assert "chunks.generation_id = documents.active_generation_id" in sql
    assert "ORDER BY chunks.document_id, chunks.index, chunks.id" in sql
