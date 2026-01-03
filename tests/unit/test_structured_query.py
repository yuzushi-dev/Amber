"""
Unit Tests for Structured Query Detection and Execution
========================================================

Tests the structured query detector, Cypher generator, and executor.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.query.structured_query import (
    StructuredQueryType,
    StructuredIntent,
    StructuredKGDetector,
    CypherGenerator,
    StructuredQueryExecutor,
)


class TestStructuredKGDetector:
    """Tests for the StructuredKGDetector class."""

    @pytest.fixture
    def detector(self):
        return StructuredKGDetector()

    # List documents patterns
    @pytest.mark.parametrize("query,expected_type", [
        ("list all documents", StructuredQueryType.LIST_DOCUMENTS),
        ("List documents", StructuredQueryType.LIST_DOCUMENTS),
        ("show all documents", StructuredQueryType.LIST_DOCUMENTS),
        ("show documents", StructuredQueryType.LIST_DOCUMENTS),
        ("get all documents", StructuredQueryType.LIST_DOCUMENTS),
        ("display documents", StructuredQueryType.LIST_DOCUMENTS),
        ("what documents do we have", StructuredQueryType.LIST_DOCUMENTS),
    ])
    def test_list_documents_detection(self, detector, query, expected_type):
        """Test detection of list documents queries."""
        intent = detector.detect(query)
        assert intent.query_type == expected_type

    # Count documents patterns
    @pytest.mark.parametrize("query,expected_type", [
        ("how many documents", StructuredQueryType.COUNT_DOCUMENTS),
        ("How many documents do we have?", StructuredQueryType.COUNT_DOCUMENTS),
        ("count all documents", StructuredQueryType.COUNT_DOCUMENTS),
        ("count documents", StructuredQueryType.COUNT_DOCUMENTS),
    ])
    def test_count_documents_detection(self, detector, query, expected_type):
        """Test detection of count documents queries."""
        intent = detector.detect(query)
        assert intent.query_type == expected_type

    # Entity patterns
    @pytest.mark.parametrize("query,expected_type", [
        ("list all entities", StructuredQueryType.LIST_ENTITIES),
        ("show entities", StructuredQueryType.LIST_ENTITIES),
        ("how many entities", StructuredQueryType.COUNT_ENTITIES),
        ("count entities", StructuredQueryType.COUNT_ENTITIES),
    ])
    def test_entity_detection(self, detector, query, expected_type):
        """Test detection of entity queries."""
        intent = detector.detect(query)
        assert intent.query_type == expected_type

    # Entity types patterns
    @pytest.mark.parametrize("query,expected_type", [
        ("list entity types", StructuredQueryType.LIST_ENTITY_TYPES),
        ("show all entity types", StructuredQueryType.LIST_ENTITY_TYPES),
        ("what types of entities exist", StructuredQueryType.LIST_ENTITY_TYPES),
    ])
    def test_entity_types_detection(self, detector, query, expected_type):
        """Test detection of entity type queries."""
        intent = detector.detect(query)
        assert intent.query_type == expected_type

    # Relationship patterns
    @pytest.mark.parametrize("query,expected_type", [
        ("list all relationships", StructuredQueryType.LIST_RELATIONSHIPS),
        ("show relationships", StructuredQueryType.LIST_RELATIONSHIPS),
    ])
    def test_relationship_detection(self, detector, query, expected_type):
        """Test detection of relationship queries."""
        intent = detector.detect(query)
        assert intent.query_type == expected_type

    # Stats patterns
    @pytest.mark.parametrize("query,expected_type", [
        ("show database stats", StructuredQueryType.DOCUMENT_STATS),
        ("get db stats", StructuredQueryType.DOCUMENT_STATS),
    ])
    def test_stats_detection(self, detector, query, expected_type):
        """Test detection of stats queries."""
        intent = detector.detect(query)
        assert intent.query_type == expected_type

    # Non-structured queries
    @pytest.mark.parametrize("query", [
        "What is machine learning?",
        "Explain the architecture of the system",
        "How does RAG work?",
        "Tell me about the documents",  # Slightly ambiguous
        "Find information about Python",
        "What are the main themes?",
    ])
    def test_non_structured_queries(self, detector, query):
        """Test that complex queries are NOT detected as structured."""
        intent = detector.detect(query)
        assert intent.query_type == StructuredQueryType.NOT_STRUCTURED

    def test_is_structured_helper(self, detector):
        """Test the is_structured helper method."""
        assert detector.is_structured("list documents") is True
        assert detector.is_structured("What is machine learning?") is False


class TestCypherGenerator:
    """Tests for the CypherGenerator class."""

    @pytest.fixture
    def generator(self):
        return CypherGenerator()

    def test_list_documents_cypher(self, generator):
        """Test Cypher generation for list documents."""
        intent = StructuredIntent(
            query_type=StructuredQueryType.LIST_DOCUMENTS,
            limit=10,
        )
        cypher, params = generator.generate(intent, "tenant_123")
        
        assert "MATCH (d:Document)" in cypher
        assert "WHERE d.tenant_id = $tenant_id" in cypher
        assert "LIMIT $limit" in cypher
        assert params["tenant_id"] == "tenant_123"
        assert params["limit"] == 10

    def test_count_entities_cypher(self, generator):
        """Test Cypher generation for count entities."""
        intent = StructuredIntent(
            query_type=StructuredQueryType.COUNT_ENTITIES,
        )
        cypher, params = generator.generate(intent, "tenant_abc")
        
        assert "MATCH (e:Entity)" in cypher
        assert "count(e)" in cypher
        assert params["tenant_id"] == "tenant_abc"

    def test_invalid_query_type_raises(self, generator):
        """Test that invalid query type raises ValueError."""
        intent = StructuredIntent(
            query_type=StructuredQueryType.NOT_STRUCTURED,
        )
        
        with pytest.raises(ValueError):
            generator.generate(intent, "tenant_123")


class TestStructuredQueryExecutor:
    """Tests for the StructuredQueryExecutor class."""

    @pytest.fixture
    def executor(self):
        return StructuredQueryExecutor()

    @pytest.mark.asyncio
    async def test_non_structured_returns_none(self, executor):
        """Test that non-structured queries return None."""
        result = await executor.try_execute(
            query="What is machine learning?",
            tenant_id="tenant_123"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_documents_execution(self, executor):
        """Test execution of list documents query."""
        mock_results = [
            {"id": "doc_1", "filename": "test.pdf", "status": "ready"},
            {"id": "doc_2", "filename": "report.docx", "status": "ready"},
        ]
        
        with patch.object(executor.detector, "detect") as mock_detect, \
             patch("src.core.query.structured_query.neo4j_client") as mock_neo4j:
            
            mock_detect.return_value = StructuredIntent(
                query_type=StructuredQueryType.LIST_DOCUMENTS,
                original_query="list documents"
            )
            
            mock_neo4j.connect = AsyncMock()
            mock_neo4j.execute_read = AsyncMock(return_value=mock_results)
            
            result = await executor.try_execute(
                query="list documents",
                tenant_id="tenant_123"
            )
            
            assert result is not None
            assert result.success is True
            assert result.query_type == StructuredQueryType.LIST_DOCUMENTS
            assert result.count == 2
            assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_count_documents_execution(self, executor):
        """Test execution of count documents query."""
        mock_results = [{"count": 42}]
        
        with patch.object(executor.detector, "detect") as mock_detect, \
             patch("src.core.query.structured_query.neo4j_client") as mock_neo4j:
            
            mock_detect.return_value = StructuredIntent(
                query_type=StructuredQueryType.COUNT_DOCUMENTS,
                original_query="how many documents"
            )
            
            mock_neo4j.connect = AsyncMock()
            mock_neo4j.execute_read = AsyncMock(return_value=mock_results)
            
            result = await executor.try_execute(
                query="how many documents",
                tenant_id="tenant_123"
            )
            
            assert result is not None
            assert result.success is True
            assert result.query_type == StructuredQueryType.COUNT_DOCUMENTS
            assert result.count == 42

    @pytest.mark.asyncio
    async def test_execution_error_returns_failure(self, executor):
        """Test that execution errors return failure result."""
        with patch.object(executor.detector, "detect") as mock_detect, \
             patch("src.core.query.structured_query.neo4j_client") as mock_neo4j:
            
            mock_detect.return_value = StructuredIntent(
                query_type=StructuredQueryType.LIST_DOCUMENTS,
                original_query="list documents"
            )
            
            mock_neo4j.connect = AsyncMock()
            mock_neo4j.execute_read = AsyncMock(side_effect=Exception("DB error"))
            
            result = await executor.try_execute(
                query="list documents",
                tenant_id="tenant_123"
            )
            
            assert result is not None
            assert result.success is False
            assert "DB error" in result.error
