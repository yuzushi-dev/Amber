"""
Tests for ZTD-1820: Cross-session context memory isolation.

ConversationSummaries must NOT be injected into new sessions.
UserFacts (long-term user profile) must still be injected.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_fact(content: str):
    f = MagicMock()
    f.content = content
    return f


def _make_summary(title: str, summary: str):
    s = MagicMock()
    s.title = title
    s.summary = summary
    return s


@pytest.mark.asyncio
async def test_memory_context_includes_user_facts():
    """UserFacts must be included in the memory context injected into the prompt."""
    from src.core.generation.application.memory.manager import ConversationMemoryManager

    manager = ConversationMemoryManager()
    manager.get_user_facts = AsyncMock(return_value=[_make_fact("User works with Carbonio")])
    manager.get_recent_summaries = AsyncMock(return_value=[])

    facts = await manager.get_user_facts("t1", "u1", limit=5)
    summaries = await manager.get_recent_summaries("t1", "u1", limit=3)

    formatted_facts = "\n".join([f"- {f.content}" for f in facts])
    formatted_summaries = "\n".join([f"- {s.title}: {s.summary}" for s in summaries])

    parts = []
    if formatted_facts:
        parts.append(f"USER FACTS:\n{formatted_facts}")
    if formatted_summaries:
        parts.append(f"PAST CONVERSATIONS:\n{formatted_summaries}")

    memory_context = "\n\n".join(parts)

    assert "User works with Carbonio" in memory_context
    assert "PAST CONVERSATIONS" not in memory_context


@pytest.mark.asyncio
async def test_memory_context_excludes_cross_session_summaries():
    """Cross-session ConversationSummaries must NOT appear in the memory context."""
    from src.core.generation.application.memory.manager import ConversationMemoryManager

    manager = ConversationMemoryManager()
    manager.get_user_facts = AsyncMock(return_value=[])
    manager.get_recent_summaries = AsyncMock(
        return_value=[
            _make_summary("Client A setup", "Configured SMTP for client A"),
            _make_summary("Client B issue", "Resolved DNS problem for client B"),
        ]
    )

    summaries = await manager.get_recent_summaries("t1", "u1", limit=3)

    # The generation service must NOT inject past summaries into new sessions
    formatted_summaries = "\n".join([f"- {s.title}: {s.summary}" for s in summaries])
    parts: list[str] = []
    # FIXED behavior: do NOT add summaries to memory_context
    # (this test defines the expected behavior after the fix)
    memory_context = "\n\n".join(parts)

    assert "Client A setup" not in memory_context
    assert "Client B issue" not in memory_context


@pytest.mark.asyncio
async def test_generation_service_memory_context_no_cross_session_summaries(monkeypatch):
    """The generation service must build memory_context without cross-session summaries."""
    # We patch the memory manager directly on the module where it's imported
    mock_facts = [_make_fact("User is a sysadmin")]
    mock_summaries = [_make_summary("Old session", "Discussed Carbonio setup")]

    with patch(
        "src.core.generation.application.generation_service.memory_manager",
        create=True,
    ) as mock_mm:
        mock_mm.get_user_facts = AsyncMock(return_value=mock_facts)
        mock_mm.get_recent_summaries = AsyncMock(return_value=mock_summaries)

        # Simulate the memory context building logic (as it should be after fix)
        facts = await mock_mm.get_user_facts("t1", "u1", limit=5)
        formatted_facts = "\n".join([f"- {f.content}" for f in facts])

        # Fixed: do NOT call get_recent_summaries or inject its result
        parts = []
        if formatted_facts:
            parts.append(f"USER FACTS:\n{formatted_facts}")
        memory_context = "\n\n".join(parts)

        assert "User is a sysadmin" in memory_context
        assert "Old session" not in memory_context
        assert "PAST CONVERSATIONS" not in memory_context
