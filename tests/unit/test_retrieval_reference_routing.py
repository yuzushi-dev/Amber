from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.retrieval.application.retrieval_service import (
    RetrievalResult,
    RetrievalService,
    _extract_article_reference,
)
from src.shared.kernel.models.query import QueryOptions, SearchMode


def _service(repository):
    factory = MagicMock()
    factory.get_embedding_provider.return_value = MagicMock()
    factory.get_llm_provider.return_value = MagicMock()
    with (
        patch("src.core.retrieval.application.retrieval_service.build_provider_factory", return_value=factory),
        patch("src.core.retrieval.application.retrieval_service.SemanticCache"),
        patch("src.core.retrieval.application.retrieval_service.ResultCache"),
    ):
        service = RetrievalService(
            document_repository=repository,
            vector_store=MagicMock(),
            neo4j_client=MagicMock(),
            openai_api_key="test-key",
        )

    service._get_effective_tenant_config = AsyncMock(return_value={})
    service.router.route = AsyncMock(return_value=SearchMode.BASIC)
    service._resolve_vector_targets = AsyncMock(return_value=[])
    service._execute_vector_search = AsyncMock(
        side_effect=lambda **kwargs: RetrievalResult(
            chunks=[],
            query=kwargs["structured_query"].cleaned_query,
            tenant_id=kwargs["tenant_id"],
            latency_ms=0,
        )
    )
    return service


def _scopes(*, shared=False, groups=False):
    return SimpleNamespace(
        effective_tenant_id="viewer",
        vector_scopes=["viewer", "owner"] if shared else ["viewer"],
        graph_scopes=["viewer"],
        group_ids=["group-1"] if groups else [],
        enforce_groups=groups,
    )


@pytest.mark.asyncio
async def test_inferred_admin_audience_is_trace_only_and_user_docs_remain_candidates():
    repo = MagicMock()
    repo.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=["user-doc"])
    service = _service(repo)

    result = await service.retrieve(
        "How do delegate admins configure VideoServer?",
        "viewer",
        query_scopes=_scopes(),
        include_trace=True,
    )

    taxonomy_call = repo.list_visible_document_ids_by_taxonomy.call_args.kwargs
    assert taxonomy_call["audience"] is None
    assert service._execute_vector_search.await_args.kwargs["document_ids"] == ["user-doc"]
    trace = next(item for item in result.trace if item["step"] == "taxonomy_routing")
    assert trace["inferred_audience"] == "admin"
    assert trace["audience_filter"] is None


@pytest.mark.asyncio
async def test_explicit_audience_with_empty_strict_result_stays_empty():
    repo = MagicMock()
    repo.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=[])
    service = _service(repo)

    result = await service.retrieve(
        "VideoServer flicker",
        "viewer",
        filters={"audience": "user"},
        query_scopes=_scopes(),
        include_trace=True,
    )

    assert repo.list_visible_document_ids_by_taxonomy.await_count == 1
    assert repo.list_visible_document_ids_by_taxonomy.call_args.kwargs["audience"] == "user"
    assert service.router.route.await_count == 0
    assert service._execute_vector_search.await_count == 0
    assert result.chunks == []
    trace = next(item for item in result.trace if item["step"] == "taxonomy_routing")
    assert trace["broadening_stage"] == "strict_empty"


@pytest.mark.asyncio
async def test_article_reference_intersects_commercial_and_shared_acl_candidates():
    repo = MagicMock()
    repo.get_editions_by_ids = AsyncMock(return_value={
        "commercial-doc": "commercial",
        "ce-doc": "ce",
        "shared-doc": "commercial",
    })

    async def visible_ids(*, viewer_tenant_id, owner_tenant_id, candidate_document_ids,
                         group_ids, enforce_groups):
        assert viewer_tenant_id == "viewer"
        assert group_ids == ["group-1"]
        assert enforce_groups
        owner_docs = ["commercial-doc", "ce-doc"] if owner_tenant_id == "viewer" else ["shared-doc"]
        if candidate_document_ids is not None:
            owner_docs = [doc for doc in owner_docs if doc in candidate_document_ids]
        return owner_docs

    async def taxonomy_ids(*, owner_tenant_id, **kwargs):
        return ["commercial-doc"] if owner_tenant_id == "viewer" else ["shared-doc"]

    repo.list_visible_document_ids = AsyncMock(side_effect=visible_ids)
    repo.list_visible_document_ids_by_taxonomy = AsyncMock(side_effect=taxonomy_ids)
    repo.find_document_ids_by_reference_number = AsyncMock(
        return_value=["shared-doc", "ce-doc", "outside-acl"]
    )
    service = _service(repo)

    result = await service.retrieve(
        "Please find KB 27632952006812",
        "viewer",
        query_scopes=_scopes(shared=True, groups=True),
        for_generation=True,
        include_trace=True,
    )

    repo.find_document_ids_by_reference_number.assert_awaited_once_with(
        "27632952006812",
        candidate_document_ids=["commercial-doc", "shared-doc"],
    )
    assert service._execute_vector_search.await_args.kwargs["document_ids"] == ["shared-doc"]
    assert next(item for item in result.trace if item["step"] == "article_reference")["status"] == "found"


@pytest.mark.asyncio
async def test_missing_article_reference_falls_back_to_normal_candidates():
    repo = MagicMock()
    repo.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=["doc-a", "doc-b"])
    repo.list_visible_document_ids = AsyncMock(side_effect=lambda **kwargs: kwargs["candidate_document_ids"])
    repo.find_document_ids_by_reference_number = AsyncMock(return_value=[])
    service = _service(repo)

    result = await service.retrieve(
        "Article 27632952006812",
        "viewer",
        query_scopes=_scopes(),
        include_trace=True,
    )

    assert service._execute_vector_search.await_args.kwargs["document_ids"] == ["doc-a", "doc-b"]
    assert next(item for item in result.trace if item["step"] == "article_reference")["status"] == "not_found"


@pytest.mark.asyncio
async def test_article_reference_lookup_error_is_traced_and_keeps_candidates():
    repo = MagicMock()
    repo.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=["doc-a", "doc-b"])
    repo.list_visible_document_ids = AsyncMock(side_effect=lambda **kwargs: kwargs["candidate_document_ids"])
    repo.find_document_ids_by_reference_number = AsyncMock(side_effect=RuntimeError("lookup failed"))
    service = _service(repo)

    result = await service.retrieve(
        "Article 27632952006812",
        "viewer",
        query_scopes=_scopes(),
        include_trace=True,
    )

    assert service._execute_vector_search.await_args.kwargs["document_ids"] == ["doc-a", "doc-b"]
    assert next(item for item in result.trace if item["step"] == "article_reference")["status"] == "error"


@pytest.mark.asyncio
async def test_explicit_empty_document_ids_return_before_rewrite_or_search():
    repo = MagicMock()
    repo.list_visible_document_ids_by_taxonomy = AsyncMock()
    repo.find_document_ids_by_reference_number = AsyncMock()
    service = _service(repo)
    service.rewriter.rewrite = AsyncMock()

    result = await service.retrieve(
        "@some-doc",
        "viewer",
        document_ids=[],
        query_scopes=_scopes(),
        history=[{"role": "user", "content": "prior"}],
        options=QueryOptions(use_rewrite=True),
    )

    assert result.chunks == []
    service.rewriter.rewrite.assert_not_awaited()
    service.router.route.assert_not_awaited()
    repo.list_visible_document_ids_by_taxonomy.assert_not_awaited()
    repo.find_document_ids_by_reference_number.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_document_ids_intersect_query_document_ids():
    repo = MagicMock()
    repo.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=["doc-a"])
    service = _service(repo)

    await service.retrieve(
        "@doc_a @doc_b",
        "viewer",
        document_ids=["doc_a", "doc_b", "doc_c"],
        query_scopes=_scopes(),
    )

    assert repo.list_visible_document_ids_by_taxonomy.call_args.kwargs["candidate_document_ids"] == [
        "doc_a",
        "doc_b",
    ]


def test_article_reference_requires_explicit_long_identifier():
    assert _extract_article_reference("Search article 27632952006812") == "27632952006812"
    assert _extract_article_reference("/articles/27632952006812") == "27632952006812"
    assert _extract_article_reference("message 27632952006812") is None
    assert _extract_article_reference("KB 27632952006812x") is None


@pytest.mark.asyncio
async def test_repository_reference_lookup_requires_candidates_and_uses_bound_exact_token():
    session = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalars.return_value.all.return_value = ["doc-a"]
    session.execute = AsyncMock(return_value=scalar_result)
    repo = PostgresDocumentRepository(session)

    assert await repo.find_document_ids_by_reference_number("1234567", ["doc-a"]) == []
    assert await repo.find_document_ids_by_reference_number("12345678", []) == []
    session.execute.assert_not_awaited()

    assert await repo.find_document_ids_by_reference_number("27632952006812", ["doc-a"]) == [
        "doc-a"
    ]
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert 'documents.id IN' in str(compiled)
    assert "~" in str(compiled)
    assert "27632952006812" not in str(compiled)
    assert "(^|[^[:alnum:]_])27632952006812([^[:alnum:]_]|$)" in compiled.params.values()
