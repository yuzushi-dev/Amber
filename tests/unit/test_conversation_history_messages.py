"""Regression test for multi-turn history re-injection.

Persisted history turns are stored as {query, answer, ...} but the query
rewriter / LLM providers consume {role, content}. Before the fix the history
was never passed at all (retrieve(history=None)), so follow-up questions were
retrieved standalone and lost context. This checks the transform that bridges
the two formats.
"""

from src.api.routes.query import _history_turns_to_messages


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
