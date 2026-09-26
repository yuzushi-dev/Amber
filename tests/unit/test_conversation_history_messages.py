"""Regression test for multi-turn history re-injection.

Persisted history turns are stored as {query, answer, ...} but the query
rewriter / LLM providers consume {role, content}. Before the fix the history
was never passed at all (retrieve(history=None)), so follow-up questions were
retrieved standalone and lost context. This checks the transform that bridges
the two formats.
"""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from src.api.routes.query import _history_turns_to_messages, _request_conversation_history
from src.api.schemas.query import QueryRequest


def test_maps_turns_to_role_content_pairs():
    # grounded turns (non-empty sources) are kept in full
    turns = [
        {"query": "cosa è UMR", "answer": "User Mail Replica ...", "sources": [1]},
        {"query": "spiega meglio le limitazioni", "answer": "Le limitazioni sono ...", "sources": [1]},
    ]
    msgs = _history_turns_to_messages(turns)
    assert msgs == [
        {"role": "user", "content": "cosa è UMR"},
        {"role": "assistant", "content": "User Mail Replica ..."},
        {"role": "user", "content": "spiega meglio le limitazioni"},
        {"role": "assistant", "content": "Le limitazioni sono ..."},
    ]


def test_client_history_validation_and_existing_caps():
    request = QueryRequest(
        query="follow up",
        history=[
            {"query": "q" * 10000, "answer": "a" * 20000},
            {"query": "second question", "answer": "second answer"},
        ],
    )
    messages = _history_turns_to_messages(
        [turn.model_dump() for turn in request.history]
    )

    assert [message["role"] for message in messages] == [
        "user", "assistant", "user", "assistant"
    ]
    assert len(messages[0]["content"]) <= 301
    assert len(messages[1]["content"]) <= 2001
    assert sum(len(message["content"]) for message in messages) <= 4600
    assert all(message["role"] != "system" for message in messages)

    with pytest.raises(ValidationError):
        QueryRequest(query="x", history=[{"query": "q"}] * 3)
    with pytest.raises(ValidationError):
        QueryRequest(query="x", history=[{"query": "q" * 10001}])
    with pytest.raises(ValidationError):
        QueryRequest(query="x", history=[{"query": "q", "answer": "a" * 20001}])
    with pytest.raises(ValidationError):
        QueryRequest(query="x", history=[{"query": "q", "role": "system"}])


@pytest.mark.asyncio
async def test_explicit_empty_client_history_skips_stored_lookup(monkeypatch):
    monkeypatch.setattr(
        "src.api.config.settings.enable_multiturn_history_reinjection", True
    )
    stored_lookup = AsyncMock(side_effect=AssertionError("stored history must not load"))
    monkeypatch.setattr("src.api.routes.query._load_conversation_history", stored_lookup)

    history = await _request_conversation_history(
        session=object(),
        request=QueryRequest(query="fresh question", history=[]),
        tenant_id="tenant-a",
        api_key_id="key-a",
    )

    assert history == []
    stored_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_omitted_client_history_keeps_flag_gated_stored_fallback(monkeypatch):
    monkeypatch.setattr(
        "src.api.config.settings.enable_multiturn_history_reinjection", True
    )
    stored = [{"role": "user", "content": "previous"}]
    stored_lookup = AsyncMock(return_value=stored)
    monkeypatch.setattr("src.api.routes.query._load_conversation_history", stored_lookup)
    session = object()

    history = await _request_conversation_history(
        session=session,
        request=QueryRequest(query="follow up", history=None, conversation_id="conv-1"),
        tenant_id="tenant-a",
        api_key_id="key-a",
    )

    assert history == stored
    stored_lookup.assert_awaited_once_with(session, "conv-1", "tenant-a", "key-a")


def test_keeps_only_last_n_turns():
    turns = [{"query": f"q{i}", "answer": f"a{i}", "sources": [1]} for i in range(10)]
    msgs = _history_turns_to_messages(turns, max_turns=2)
    # last 2 turns → 4 messages, and they are q8/q9
    assert [m["content"] for m in msgs] == ["q8", "a8", "q9", "a9"]


def test_default_window_survives_rewriter_5msg_slice():
    # Default caps at 2 turns = 4 messages, so QueryRewriter's history[-5:]
    # keeps them intact and starts on a user message (never mid-turn).
    turns = [{"query": f"q{i}", "answer": f"a{i}", "sources": [1]} for i in range(5)]
    msgs = _history_turns_to_messages(turns)
    assert len(msgs) == 4
    assert msgs[0] == {"role": "user", "content": "q3"}
    assert msgs[-1] == {"role": "assistant", "content": "a4"}


def test_drops_refusal_assistant_turn_keeps_user():
    # A refusal answer must not be re-fed as assistant context (retrieval
    # poisoning); the user's question is still kept.
    turns = [
        {"query": "come sposto consul", "answer": "I don't have documentation on that.", "sources": []},
        {"query": "e le limitazioni?", "answer": "Le limitazioni sono ...", "sources": [1]},
    ]
    msgs = _history_turns_to_messages(turns)
    assert {"role": "assistant", "content": "I don't have documentation on that."} not in msgs
    assert {"role": "user", "content": "come sposto consul"} in msgs
    assert {"role": "assistant", "content": "Le limitazioni sono ..."} in msgs


def test_skips_missing_fields_and_empty():
    assert _history_turns_to_messages([]) == []
    assert _history_turns_to_messages(None) == []
    # a turn with only a query (no answer yet) contributes just the user msg
    assert _history_turns_to_messages([{"query": "solo domanda"}]) == [
        {"role": "user", "content": "solo domanda"}
    ]


if __name__ == "__main__":
    test_maps_turns_to_role_content_pairs()
    test_keeps_only_last_n_turns()
    test_skips_missing_fields_and_empty()
    print("ok")
