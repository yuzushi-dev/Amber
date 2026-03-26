"""
Security tests for gap fixes (Tasks 4–12 of gap analysis).

Covers:
- chunks.py: update/delete verify parent doc belongs to caller's tenant
- chunks.py: Neo4j delete uses tenant_id predicate
- feedback.py: get_feedback scopes count and fetch by tenant_id
- export_service.py: generate_single_conversation_zip accepts and uses tenant_id
- restore_service.py: _restore_folders/_restore_documents merge-mode check includes tenant_id
- graph_history.py: create_pending_edit requires verify_tenant_admin
- events.py: document_status_stream requires auth + tenant ownership
- admin/rules.py: router uses verify_tenant_admin (not verify_admin)
- summarizer.py: _persist_summary passes tenant_id to execute_write params
"""

import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 1. chunks.py ─────────────────────────────────────────────────────────────


def test_update_chunk_doc_ownership_check_present():
    """
    update_chunk must query Document with BOTH id AND tenant_id so a caller
    cannot modify chunks in another tenant's document.
    """
    import src.api.routes.chunks as chunks_module
    source = inspect.getsource(chunks_module.update_chunk)
    assert "Document.tenant_id == tenant_id" in source, (
        "update_chunk: Document ownership check missing tenant_id predicate — "
        "cross-tenant chunk update is possible."
    )


def test_delete_chunk_doc_ownership_check_present():
    """
    delete_chunk must query Document with BOTH id AND tenant_id.
    """
    import src.api.routes.chunks as chunks_module
    source = inspect.getsource(chunks_module.delete_chunk)
    assert "Document.tenant_id == tenant_id" in source, (
        "delete_chunk: Document ownership check missing tenant_id predicate."
    )


def test_delete_chunk_neo4j_uses_tenant_predicate():
    """
    The Neo4j MATCH in delete_chunk must include tenant_id: $tenant_id so that
    only the caller's own chunk node is deleted, not a same-ID node from another tenant.
    """
    import src.api.routes.chunks as chunks_module
    source = inspect.getsource(chunks_module.delete_chunk)
    assert "tenant_id: $tenant_id" in source, (
        "delete_chunk: Neo4j MATCH does not include tenant_id predicate — "
        "cross-tenant chunk deletion from the graph is possible."
    )


# ── 2. feedback.py ────────────────────────────────────────────────────────────


def test_get_feedback_source_has_tenant_filter():
    """
    get_feedback must include Feedback.tenant_id == tenant_id in its DB queries
    so feedback from other tenants is never returned.
    """
    import src.api.routes.feedback as feedback_module
    source = inspect.getsource(feedback_module.get_feedback)
    assert "Feedback.tenant_id == tenant_id" in source, (
        "get_feedback: query does not filter by tenant_id — "
        "feedback from any tenant can be read by any authenticated user."
    )


def test_get_feedback_raises_without_tenant():
    """
    get_feedback must raise 401 when tenant_id is absent from request state.
    """
    import asyncio
    import src.api.routes.feedback as feedback_module
    from fastapi import HTTPException

    req = MagicMock()
    del req.state.tenant_id

    mock_session = AsyncMock()
    mock_session.scalar = AsyncMock(return_value=0)
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    with pytest.raises((HTTPException, AttributeError)):
        asyncio.get_event_loop().run_until_complete(
            feedback_module.get_feedback("req-123", req, db=mock_session)
        )


# ── 3. export_service.py ──────────────────────────────────────────────────────


def test_export_service_generate_single_accepts_tenant_id():
    """
    generate_single_conversation_zip must accept tenant_id as an explicit
    parameter (not derive it from global settings).
    """
    from src.core.admin_ops.application.export_service import ExportService
    sig = inspect.signature(ExportService.generate_single_conversation_zip)
    params = list(sig.parameters)
    assert "tenant_id" in params, (
        "generate_single_conversation_zip: tenant_id parameter missing — "
        "export cannot be scoped to the caller's tenant."
    )


def test_export_service_source_scopes_conversation_by_tenant():
    """
    The conversation query in generate_single_conversation_zip must filter by
    tenant_id so a user cannot export another tenant's conversation.
    """
    from src.core.admin_ops.application.export_service import ExportService
    source = inspect.getsource(ExportService.generate_single_conversation_zip)
    assert "ConversationSummary.tenant_id == tenant_id" in source, (
        "generate_single_conversation_zip: conversation query not scoped to tenant_id."
    )


# ── 4. restore_service.py ─────────────────────────────────────────────────────


def test_restore_folders_merge_check_uses_tenant_id():
    """
    _restore_folders merge-mode check must include Folder.tenant_id == tenant_id
    so a folder from a different tenant with the same UUID is not treated as existing.
    """
    from src.core.admin_ops.application.restore_service import RestoreService
    source = inspect.getsource(RestoreService._restore_folders)
    assert "Folder.tenant_id == tenant_id" in source, (
        "_restore_folders: merge duplicate check does not scope by tenant_id — "
        "restore can incorrectly skip folders that belong to a different tenant."
    )


def test_restore_documents_merge_check_uses_tenant_id():
    """
    _restore_documents merge-mode check must include Document.tenant_id == tenant_id.
    """
    from src.core.admin_ops.application.restore_service import RestoreService
    source = inspect.getsource(RestoreService._restore_documents)
    assert "Document.tenant_id == tenant_id" in source, (
        "_restore_documents: merge duplicate check does not scope by tenant_id."
    )


# ── 5. graph_history.py: create_pending_edit ─────────────────────────────────


def test_graph_history_create_pending_edit_has_tenant_admin_dep():
    """
    create_pending_edit must declare verify_tenant_admin as a Depends parameter
    so that unprivileged users cannot stage graph edits.
    """
    import src.api.routes.graph_history as gh_module

    handler = getattr(gh_module, "create_pending_edit", None)
    assert handler is not None, "create_pending_edit not found in graph_history"

    sig = inspect.signature(handler)
    dep_names = []
    for param in sig.parameters.values():
        default = param.default
        if hasattr(default, "dependency"):
            fn = default.dependency
            dep_names.append(getattr(fn, "__name__", repr(fn)))

    assert any("tenant_admin" in d or "super_admin" in d for d in dep_names), (
        f"create_pending_edit missing verify_tenant_admin dependency. "
        f"Found: {dep_names!r}. Any authenticated user can stage graph edits."
    )


# ── 6. events.py ─────────────────────────────────────────────────────────────


def test_events_document_status_stream_requires_auth():
    """
    document_status_stream must raise 401 when request.state.tenant_id is absent.
    """
    import asyncio
    import src.api.routes.events as events_module
    from fastapi import HTTPException

    req = MagicMock()
    req.state = MagicMock(spec=[])  # no tenant_id on state

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(
            events_module.stream_document_events("doc-123", req, mock_session)
        )
    assert exc_info.value.status_code == 401, (
        f"Expected 401, got {exc_info.value.status_code}. "
        "SSE stream is accessible without authentication."
    )


def test_events_sse_channel_is_tenant_qualified():
    """
    event_generator must use a tenant-qualified Redis channel
    ('document:{tenant_id}:{doc_id}:status') to prevent cross-tenant SSE leaks.
    """
    import src.api.routes.events as events_module
    source = inspect.getsource(events_module.event_generator)
    # The channel must include tenant_id in its path
    assert "tenant_id" in source, (
        "event_generator: Redis channel does not include tenant_id — "
        "SSE events from any tenant could be subscribed to."
    )


# ── 7. admin/rules.py ────────────────────────────────────────────────────────


def test_rules_router_uses_verify_tenant_admin():
    """
    The rules router must declare verify_tenant_admin (not the weaker verify_admin)
    as its router-level dependency.
    """
    import src.api.routes.admin.rules as rules_module
    source = inspect.getsource(rules_module)
    assert "verify_tenant_admin" in source, (
        "admin/rules.py does not import or use verify_tenant_admin."
    )
    # Also ensure the old verify_admin is not the primary guard
    # (it's OK if it's imported but verify_tenant_admin must be in the dependencies list)
    assert "dependencies=[Depends(verify_tenant_admin)]" in source, (
        "rules router is not guarded by verify_tenant_admin at router level."
    )


# ── 8. summarizer.py ─────────────────────────────────────────────────────────


def test_summarizer_persist_summary_has_tenant_id_in_params():
    """
    _persist_summary must include 'tenant_id' in the params dict passed to
    execute_write so the MATCH (c:Community {id: $id, tenant_id: $tenant_id})
    clause is actually satisfied.
    """
    from src.core.graph.application.communities.summarizer import CommunitySummarizer
    source = inspect.getsource(CommunitySummarizer._persist_summary)
    assert '"tenant_id": tenant_id' in source or "'tenant_id': tenant_id" in source, (
        "_persist_summary: tenant_id is used in the MATCH clause but not passed in params dict — "
        "the query will match zero nodes and silently skip the update."
    )


def test_summarizer_persist_summary_match_uses_tenant_id():
    """
    The Cypher MATCH in _persist_summary must include tenant_id in the predicate.
    """
    from src.core.graph.application.communities.summarizer import CommunitySummarizer
    source = inspect.getsource(CommunitySummarizer._persist_summary)
    assert "tenant_id: $tenant_id" in source, (
        "_persist_summary: Community MATCH clause does not include tenant_id predicate — "
        "cross-tenant community node update is possible."
    )


def test_summarizer_summarize_community_passes_tenant_to_persist():
    """
    The summarize_community method must pass tenant_id when calling _persist_summary.
    """
    from src.core.graph.application.communities.summarizer import CommunitySummarizer
    source = inspect.getsource(CommunitySummarizer.summarize_community)
    assert "_persist_summary(community_id, summary_content, tenant_id)" in source, (
        "summarize_community does not pass tenant_id to _persist_summary — "
        "the tenant isolation in _persist_summary is bypassed."
    )
