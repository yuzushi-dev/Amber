"""
Security tests for agent tool authorization — Task 2.

These tests verify that:
- agent_role=maintainer is restricted to super_admin callers
- Filesystem tools reject path traversal
- Feature flags default to False (disabled) in production config

Run BEFORE applying the fix to see failures, AFTER to confirm all pass.
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

# ── Feature flag defaults ─────────────────────────────────────────────────────


def test_enable_agent_mode_field_exists_and_defaults_false():
    """Settings must have enable_agent_mode defaulting to False."""
    from src.api.config import Settings

    field = Settings.model_fields.get("enable_agent_mode")
    assert field is not None, "enable_agent_mode field missing from Settings"
    assert field.default is False, f"expected False, got {field.default}"


def test_enable_maintainer_tools_field_exists_and_defaults_false():
    """Settings must have enable_maintainer_tools defaulting to False."""
    from src.api.config import Settings

    field = Settings.model_fields.get("enable_maintainer_tools")
    assert field is not None, "enable_maintainer_tools field missing from Settings"
    assert field.default is False, f"expected False, got {field.default}"


def test_enable_agent_graph_tool_field_exists_and_defaults_false():
    """Settings must have enable_agent_graph_tool defaulting to False."""
    from src.api.config import Settings

    field = Settings.model_fields.get("enable_agent_graph_tool")
    assert field is not None, "enable_agent_graph_tool field missing from Settings"
    assert field.default is False, f"expected False, got {field.default}"


# ── Filesystem path traversal ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_path_traversal_read_file_rejected():
    """read_file must reject path traversal outside the base directory."""
    from src.core.tools.filesystem import create_filesystem_tools

    with tempfile.TemporaryDirectory() as base:
        secret_file = os.path.join(os.path.dirname(base), "secret_outer.txt")
        try:
            with open(secret_file, "w") as f:
                f.write("TOP_SECRET")

            tools = create_filesystem_tools(base_path=base)
            read_file = next(t["func"] for t in tools if t["name"] == "read_file")

            result = await read_file("../secret_outer.txt")
            assert "TOP_SECRET" not in result, \
                f"Path traversal succeeded, secret was leaked: {result!r}"
            assert "error" in result.lower() or "denied" in result.lower(), \
                f"Expected error/denied response, got: {result!r}"
        finally:
            if os.path.exists(secret_file):
                os.unlink(secret_file)


@pytest.mark.asyncio
async def test_path_traversal_absolute_rejected():
    """read_file must reject absolute paths that escape the base directory."""
    from src.core.tools.filesystem import create_filesystem_tools

    with tempfile.TemporaryDirectory() as base:
        tools = create_filesystem_tools(base_path=base)
        read_file = next(t["func"] for t in tools if t["name"] == "read_file")

        # Attempt absolute path traversal via /../ chain
        result = await read_file("../../etc/hostname")
        assert "error" in result.lower() or "denied" in result.lower(), \
            f"Expected error/denied response, got: {result!r}"


@pytest.mark.asyncio
async def test_path_traversal_list_directory_rejected():
    """list_directory must reject traversal outside the base directory."""
    from src.core.tools.filesystem import create_filesystem_tools

    with tempfile.TemporaryDirectory() as base:
        tools = create_filesystem_tools(base_path=base)
        list_dir = next(t["func"] for t in tools if t["name"] == "list_directory")

        result = await list_dir("../../etc")
        assert "error" in result.lower() or "denied" in result.lower(), \
            f"Expected error/denied response, got: {result!r}"


@pytest.mark.asyncio
async def test_filesystem_tools_allow_paths_within_base():
    """Filesystem tools must allow valid relative paths inside the base directory."""
    from src.core.tools.filesystem import create_filesystem_tools

    with tempfile.TemporaryDirectory() as base:
        # Create a file and subdirectory inside base
        inner = os.path.join(base, "subdir")
        os.makedirs(inner)
        test_file = os.path.join(inner, "data.txt")
        with open(test_file, "w") as f:
            f.write("safe content")

        tools = create_filesystem_tools(base_path=base)
        read_file = next(t["func"] for t in tools if t["name"] == "read_file")
        list_dir = next(t["func"] for t in tools if t["name"] == "list_directory")

        result = await read_file("subdir/data.txt")
        assert "safe content" in result, f"Expected file content, got: {result!r}"

        result = await list_dir("subdir")
        assert "data.txt" in result, f"Expected directory listing, got: {result!r}"


# ── Maintainer role privilege check ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_maintainer_role_raises_403_for_tenant_user():
    """agent_role=maintainer must raise HTTP 403 for non-super-admin callers."""
    from src.core.retrieval.application.use_cases_query import QueryUseCase
    from src.shared.kernel.models.query import QueryOptions, QueryRequest

    state = MagicMock()
    state.is_super_admin = False

    uc = QueryUseCase(
        retrieval_service=AsyncMock(),
        generation_service=AsyncMock(),
        metrics_collector=AsyncMock(),
    )
    request = QueryRequest(
        query="list all source files",
        options=QueryOptions(agent_mode=True, agent_role="maintainer"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await uc.execute(
            request=request,
            tenant_id="test-tenant",
            http_request_state=state,
        )
    assert exc_info.value.status_code == 403, \
        f"Expected 403, got {exc_info.value.status_code}"


@pytest.mark.asyncio
async def test_agent_mode_raises_403_when_disabled():
    """agent_mode=True must raise HTTP 403 when ENABLE_AGENT_MODE is False."""
    from unittest.mock import patch

    from src.core.retrieval.application.use_cases_query import QueryUseCase
    from src.shared.kernel.models.query import QueryOptions, QueryRequest

    state = MagicMock()
    state.is_super_admin = True  # even super_admin blocked when mode is off

    uc = QueryUseCase(
        retrieval_service=AsyncMock(),
        generation_service=AsyncMock(),
        metrics_collector=AsyncMock(),
    )
    request = QueryRequest(
        query="test query",
        options=QueryOptions(agent_mode=True, agent_role="knowledge"),
    )

    mock_settings = MagicMock()
    mock_settings.enable_agent_mode = False
    mock_settings.enable_maintainer_tools = False
    mock_settings.enable_agent_graph_tool = False

    with patch("src.api.config.settings", mock_settings):
        with pytest.raises(HTTPException) as exc_info:
            await uc.execute(
                request=request,
                tenant_id="test-tenant",
                http_request_state=state,
            )
    assert exc_info.value.status_code == 403, \
        f"Expected 403, got {exc_info.value.status_code}"
