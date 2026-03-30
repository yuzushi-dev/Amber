"""
Security tests for Task 6: tenant isolation for graph surfaces.

Covers:
- graph_editor.py write ops require tenant_admin role
- graph_history.py apply/reject/undo require tenant_admin role
- context_writer.py Cypher MATCH queries include tenant_id predicates
"""

import inspect
from unittest.mock import MagicMock

import pytest

# ── Helper ────────────────────────────────────────────────────────────────────


def _non_admin_request():
    req = MagicMock()
    req.state.is_super_admin = False
    req.state.tenant_role = None   # not an admin
    req.state.permissions = ["active_user"]
    req.state.tenant_id = "tenant-abc"
    return req


# ── graph_editor.py: write ops require tenant_admin ──────────────────────────


@pytest.mark.asyncio
async def test_graph_editor_heal_requires_tenant_admin():
    """heal_node must reject non-admin callers with 403."""
    from fastapi import HTTPException

    from src.api.deps import verify_tenant_admin

    req = _non_admin_request()
    with pytest.raises(HTTPException) as exc_info:
        await verify_tenant_admin(req)
    assert exc_info.value.status_code == 403


def test_graph_editor_write_handlers_have_tenant_admin_dependency():
    """
    heal_node, merge_nodes, create_edge, delete_edge, delete_node must all
    declare verify_tenant_admin (or verify_super_admin) as a Depends parameter.
    """
    import src.api.routes.graph_editor as ge_module

    write_ops = ["heal_node", "merge_nodes", "create_edge", "delete_edge", "delete_node"]
    for op_name in write_ops:
        handler = getattr(ge_module, op_name, None)
        assert handler is not None, f"Handler '{op_name}' not found in graph_editor"
        sig = inspect.signature(handler)
        dep_names = []
        for param in sig.parameters.values():
            default = param.default
            if hasattr(default, "dependency"):
                fn = default.dependency
                dep_names.append(getattr(fn, "__name__", repr(fn)))
        assert any(
            "tenant_admin" in d or "super_admin" in d for d in dep_names
        ), (
            f"graph_editor.{op_name} missing verify_tenant_admin dependency. "
            f"Found: {dep_names!r}. Any authenticated user can modify the knowledge graph."
        )


# ── graph_history.py: apply/reject/undo require tenant_admin ─────────────────


def test_graph_history_mutating_handlers_have_tenant_admin_dependency():
    """
    apply_pending_edit, reject_pending_edit, undo_applied_edit must declare
    verify_tenant_admin as a Depends parameter.
    """
    import src.api.routes.graph_history as gh_module

    mutating_ops = ["apply_pending_edit", "reject_pending_edit", "undo_applied_edit"]
    for op_name in mutating_ops:
        handler = getattr(gh_module, op_name, None)
        assert handler is not None, f"Handler '{op_name}' not found in graph_history"
        sig = inspect.signature(handler)
        dep_names = []
        for param in sig.parameters.values():
            default = param.default
            if hasattr(default, "dependency"):
                fn = default.dependency
                dep_names.append(getattr(fn, "__name__", repr(fn)))
        assert any(
            "tenant_admin" in d or "super_admin" in d for d in dep_names
        ), (
            f"graph_history.{op_name} missing verify_tenant_admin dependency. "
            f"Found: {dep_names!r}."
        )


# ── context_writer.py: all MATCH queries include tenant_id ───────────────────


def _get_context_writer_source() -> str:
    import src.core.graph.application.context_writer as cw_module
    return inspect.getsource(cw_module)


def _find_bare_id_lines(source: str) -> list[tuple[int, str]]:
    """
    Return (lineno, text) tuples for lines that contain {{id: $... (f-string literal
    brace for Cypher {id: $param}) without a tenant_id predicate on the same line.
    Also catch plain {id: $param} patterns (non-f-string blocks).
    """
    bad = []
    for i, line in enumerate(source.split("\n"), 1):
        stripped = line.strip()
        has_bare_id = (
            ("{{id: $" in line or "{id: $" in line)
            and "tenant_id" not in line
            and ("MATCH" in line or "MERGE" in line)
        )
        if has_bare_id:
            bad.append((i, stripped))
    return bad


def test_context_writer_no_bare_id_match():
    """
    No MATCH/MERGE in context_writer.py should identify nodes by bare id
    ({{id: $param}}) without also including tenant_id on the same line.
    """
    source = _get_context_writer_source()
    bad = _find_bare_id_lines(source)
    assert not bad, (
        "context_writer.py contains bare-ID node lookups missing tenant_id:\n"
        + "\n".join(f"  line {n}: {t}" for n, t in bad)
    )


def test_context_writer_log_turn_passes_tenant_to_link_query():
    """
    The log_turn Conversation→Turn link execute_write call must pass
    tenant_id in its parameters dict so MATCH clauses can scope by tenant.
    """
    source = _get_context_writer_source()
    import re
    # Find the params dict near the HAS_TURN MERGE call
    # After fix it should contain "tenant_id": tenant_id
    re.search(
        r'HAS_TURN.*?"(conv_id|turn_id)".*?',
        source,
        re.DOTALL,
    )
    # Simpler: just check that "tenant_id" appears in the params dicts
    # that are near the execute_write blocks for linking
    # We verify via the no_bare_id_match test above; this one checks params
    link_section = re.search(
        r'# 3\. Link Conversation.*?execute_write\(.*?(\{[^}]+\})\s*\)',
        source,
        re.DOTALL,
    )
    if link_section:
        assert "tenant_id" in link_section.group(0), (
            "log_turn link query execute_write params dict missing tenant_id"
        )


def test_context_writer_conversation_link_has_tenant_predicate():
    """Alias for clarity — same as test_context_writer_no_bare_id_match."""
    source = _get_context_writer_source()
    bad = _find_bare_id_lines(source)
    assert not bad, (
        "Bare-ID node links found: " + str(bad)
    )
