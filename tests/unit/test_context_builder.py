import subprocess
import sys

import pytest

from src.core.generation.application.context_builder import ContextBuilder
from src.core.utils import tokenizer
from src.core.utils.tokenizer import Tokenizer


@pytest.fixture(autouse=True)
def use_character_fallback_for_context_builder_tests(monkeypatch):
    # Keep builder unit cases on the real character-prefix fallback; tiktoken
    # multibyte decoding is covered in an isolated subprocess below.
    monkeypatch.setattr(tokenizer, "TIKTOKEN_AVAILABLE", False)


def test_context_builder_budget():
    candidates = [
        {"content": "First chunk content.", "chunk_id": "1"},
        {"content": "Second chunk content that is a bit longer.", "chunk_id": "2"},
        {"content": "Third chunk content.", "chunk_id": "3"},
    ]

    # Very small budget
    builder = ContextBuilder(max_tokens=20)
    result = builder.build(candidates)

    assert len(result.used_candidates) < 3
    assert result.tokens <= 20
    assert "First chunk" in result.content


def test_sentence_truncation():
    text = "This is sentence one. This is sentence two! And sentence three?"
    builder = ContextBuilder(max_tokens=60)  # Should fit about 1-2 sentences

    # Mocking a candidate with long text
    candidates = [{"content": text * 10, "chunk_id": "long"}]
    result = builder.build(candidates)

    # Check that it ends with punctuation
    assert result.content.strip()[-1] in ".!?"
    assert result.tokens <= 60


def test_metadata_inclusion():
    candidates = [{"content": "Content", "title": "Secret Document"}]
    builder = ContextBuilder()
    result = builder.build(candidates)

    assert "Source ID: 1" in result.content
    assert "Document: Secret Document" in result.content


def test_context_includes_canonical_title_and_document_id_and_skips_empty_ids():
    candidates = [
        {"chunk_id": "empty", "document_id": "doc-empty", "content": ""},
        {"chunk_id": "mail", "document_id": "27632952006812", "content": "Mail article body."},
    ]

    result = ContextBuilder().build(
        candidates,
        document_titles={"27632952006812": "View Mail article 27632952006812"},
    )

    assert "[Source ID: 1]" in result.content
    assert "[Document ID: 27632952006812]" in result.content
    assert "[Document: View Mail article 27632952006812]" in result.content
    assert "Source ID: 2" not in result.content
    assert result.used_candidates == [candidates[1]]


def test_context_source_ids_skip_candidates_dropped_by_budget():
    candidates = [
        {"chunk_id": "large", "content": "A very large candidate that cannot fit into this small context budget."},
        {"chunk_id": "small", "content": "Short."},
    ]

    result = ContextBuilder(max_tokens=20).build(candidates)

    assert [candidate["chunk_id"] for candidate in result.used_candidates] == ["small"]
    assert "[Source ID: 1]" in result.content
    assert "Source ID: 2" not in result.content


def test_context_drops_candidate_when_long_title_alone_exceeds_budget():
    result = ContextBuilder(max_tokens=60).build(
        [{"chunk_id": "long-title", "document_id": "doc", "content": "Short body."}],
        document_titles={"doc": "Very long title " * 80},
    )

    assert result.content == ""
    assert result.tokens == Tokenizer.count_tokens(result.content)
    assert result.tokens <= 60
    assert result.dropped_candidates[0]["chunk_id"] == "long-title"
    assert result.coverage == [
        {
            "chunk_id": "long-title",
            "document_id": "doc",
            "source_id": None,
            "original_chars": len("Short body."),
            "post_pii_chars": len("Short body."),
            "presented_chars": 0,
            "truncated": False,
            "omitted": True,
            "reason": "budget",
            "synthetic": False,
        }
    ]
    assert result.source_excerpts == {}


def test_small_context_overrun_keeps_near_budget_body_prefix():
    raw = "A" * 1000
    result = ContextBuilder(max_tokens=60).build([{"chunk_id": "near-budget", "content": raw}])

    presented = result.content.split("\n", 1)[1]
    body_prefix = presented[:-3]
    assert result.tokens <= 60
    assert result.tokens == Tokenizer.count_tokens(result.content)
    assert len(body_prefix) > 180
    assert raw.startswith(body_prefix)
    assert presented.endswith("...")


@pytest.mark.parametrize(
    ("raw", "expected_prefix", "sensitive_text"),
    [
        (
            "  Keep indentation. support@example.com\n    Keep nested indentation. " * 12,
            "  Keep indentation.",
            "support@example.com",
        ),
        (("🙂" * 20 + " end. ") * 12, "🙂", None),
    ],
    ids=["preserve-whitespace-and-pii-coverage", "unicode-true-prefix-coverage"],
)
def test_context_truncation_budget_unicode_whitespace_coverage(raw, expected_prefix, sensitive_text):
    result = ContextBuilder(max_tokens=60).build(
        [{"chunk_id": "mail", "document_id": "doc", "content": raw}]
    )

    assert result.tokens == Tokenizer.count_tokens(result.content)
    assert result.tokens <= 60
    coverage = result.coverage[0]
    presented = result.content.split("\n", 1)[1]
    body_prefix = presented[:-3] if coverage["truncated"] else presented
    assert body_prefix.startswith(expected_prefix)
    if sensitive_text:
        assert raw.startswith(body_prefix.replace("s***@example.com", sensitive_text))
    else:
        assert raw.startswith(body_prefix)
    assert "\ufffd" not in presented
    if sensitive_text:
        assert sensitive_text not in presented
        assert coverage["post_pii_chars"] < len(raw)
    else:
        assert coverage["post_pii_chars"] == len(raw)
    assert coverage["original_chars"] == len(raw)
    assert coverage["presented_chars"] == len(presented)
    assert coverage["source_id"] == 1
    assert coverage["truncated"] is True
    assert coverage["omitted"] is False
    assert coverage["reason"] == "truncated"
    assert "content" not in coverage
    assert result.source_excerpts == {1: body_prefix}


def test_real_tiktoken_unicode_truncation_is_a_source_prefix_in_subprocess():
    script = """
from src.core.generation.application.context_builder import ContextBuilder
from src.core.utils.tokenizer import Tokenizer

assert Tokenizer.get_encoding() is not None
text = "🙂" * 100
truncated = ContextBuilder()._truncate_at_sentence(text, 3)
assert text.startswith(truncated)
assert truncated
assert "\\ufffd" not in truncated
suffix = Tokenizer.truncate_to_budget(text, 3, from_start=False)
assert text.endswith(suffix)
assert suffix
with_replacement = "A\\ufffd" * 100
preserved = Tokenizer.truncate_to_budget(with_replacement, 10)
assert with_replacement.startswith(preserved)
assert "\\ufffd" in preserved
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)


def test_empty_and_synthetic_candidates_have_coverage_but_source_ids_only_when_used():
    candidates = [
        {"chunk_id": "empty", "document_id": "empty-doc", "content": ""},
        {
            "chunk_id": "rule",
            "content": "Rule text.",
            "metadata": {"synthetic": True},
        },
        {"chunk_id": "large", "content": "Large body " * 100},
        {"chunk_id": "small", "content": "Short."},
    ]
    result = ContextBuilder(max_tokens=20).build(candidates)

    assert [c["chunk_id"] for c in result.used_candidates] == ["rule", "small"]
    assert result.coverage[0]["reason"] == "empty_content"
    assert result.coverage[0]["source_id"] is None
    assert result.coverage[0]["omitted"] is True
    assert result.coverage[1]["source_id"] == 1
    assert result.coverage[1]["synthetic"] is True
    assert result.source_excerpts == {2: "Short."}
    assert result.coverage[2]["source_id"] is None
    assert result.coverage[2]["reason"] == "budget"
    assert result.coverage[3]["source_id"] == 2
    assert result.coverage[3]["reason"] == "included"
