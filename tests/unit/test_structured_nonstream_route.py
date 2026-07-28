"""Regression test: POST /v1/query must return structured results, not the fallback.

The route is declared `-> QueryResponse | StructuredQueryResponse`, but the
conversation-persistence block read `response.conversation_id` unconditionally.
StructuredQueryResponse has no such field, so every structured query raised
AttributeError, which the surrounding broad `except Exception` converted into the
generic "I'm unable to process your query at the moment" fallback.

The assertion is on the returned object, not on the absence of an exception:
the bug never propagated an exception to the caller, it produced a wrong 200.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.routes.query import query
from src.api.schemas.query import QueryOptions, QueryRequest
from src.shared.kernel.models.query import StructuredQueryResponse, TimingInfo


def _http_request():
    return SimpleNamespace(
        method="POST",
        state=SimpleNamespace(tenant_id="default", query_scopes=None, is_super_admin=False),
        headers={"X-User-ID": "tester"},
    )


def _structured_response():
    return StructuredQueryResponse(
        query_type="list_documents",
        data=[{"filename": "a.html"}, {"filename": "b.html"}],
        count=2,
        timing=TimingInfo(total_ms=1.0, retrieval_ms=1.0, generation_ms=0.0),
    )


@pytest.mark.asyncio
async def test_structured_query_is_returned_not_swallowed_into_fallback():
    expected = _structured_response()

    use_case = MagicMock()
    use_case.execute = AsyncMock(return_value=expected)

    with (
        patch("src.amber_platform.composition_root.build_retrieval_service", MagicMock()),
        patch("src.amber_platform.composition_root.build_generation_service", MagicMock()),
        patch("src.amber_platform.composition_root.build_metrics_collector", MagicMock()),
        patch(
            "src.core.retrieval.application.use_cases_query.QueryUseCase",
            return_value=use_case,
        ),
    ):
        result = await query(
            request=QueryRequest(
                query="list all documents",
                options=QueryOptions(include_sources=True),
            ),
            http_request=_http_request(),
            session=MagicMock(),
        )

    assert isinstance(result, StructuredQueryResponse), (
        f"structured query fell back to an error response: {getattr(result, 'answer', result)!r}"
    )
    assert result.count == 2
    assert result.query_type == "list_documents"
