"""
Unit tests for QueryParser
"""

from datetime import datetime

from src.core.query.parser import QueryParser


def test_parser_basic():
    query = "What is the capital of France?"
    parsed = QueryParser.parse(query)

    assert parsed.original_query == query
    assert parsed.cleaned_query == query
    assert parsed.document_ids == []
    assert parsed.tags == []
    assert parsed.date_after is None
    assert parsed.date_before is None


def test_parser_with_filters():
    query = "What are the benefits? @doc1 #hr since:2023-01-01 until:2023-12-31"
    parsed = QueryParser.parse(query)

    assert "benefits" in parsed.cleaned_query
    assert "doc1" in parsed.document_ids
    assert "hr" in parsed.tags
    assert parsed.date_after == datetime(2023, 1, 1)
    assert parsed.date_before == datetime(2023, 12, 31)

    # Check that patterns are removed from cleaned_query
    assert "@" not in parsed.cleaned_query
    assert "#" not in parsed.cleaned_query
    assert "since:" not in parsed.cleaned_query
    assert "until:" not in parsed.cleaned_query


def test_parser_multiple_filters():
    query = "@doc1 @doc2 #tag1 #tag2 tell me more"
    parsed = QueryParser.parse(query)

    assert parsed.document_ids == ["doc1", "doc2"]
    assert parsed.tags == ["tag1", "tag2"]
    assert parsed.cleaned_query == "tell me more"


def test_parser_only_filters():
    query = "@doc1 #tag1"
    parsed = QueryParser.parse(query)

    assert parsed.document_ids == ["doc1"]
    assert parsed.tags == ["tag1"]
    # Should fallback to original query if cleaned is empty
    assert parsed.cleaned_query == query
