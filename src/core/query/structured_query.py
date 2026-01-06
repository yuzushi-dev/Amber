"""
Structured Query Executor
=========================

Detects and executes structured queries (list, count, aggregate) directly via Cypher.
Bypasses the RAG pipeline for queries that can be answered with direct database access.

Examples:
- "List all documents" -> Direct Cypher query
- "How many entities are there?" -> COUNT query
- "Show documents about machine learning" -> Filtered list query
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.core.graph.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)


class StructuredQueryType(str, Enum):
    """Types of structured queries that can be executed directly."""

    LIST_DOCUMENTS = "list_documents"
    COUNT_DOCUMENTS = "count_documents"
    LIST_ENTITIES = "list_entities"
    COUNT_ENTITIES = "count_entities"
    LIST_ENTITY_TYPES = "list_entity_types"
    LIST_RELATIONSHIPS = "list_relationships"
    COUNT_CHUNKS = "count_chunks"
    DOCUMENT_STATS = "document_stats"
    NOT_STRUCTURED = "not_structured"


@dataclass
class StructuredIntent:
    """Parsed intent from a structured query."""

    query_type: StructuredQueryType
    filters: dict = field(default_factory=dict)  # e.g., {"entity_type": "Person"}
    limit: int = 50
    offset: int = 0
    original_query: str = ""


@dataclass
class StructuredResult:
    """Result from a structured query execution."""

    success: bool
    query_type: StructuredQueryType
    data: list[dict[str, Any]] = field(default_factory=list)
    count: int = 0
    cypher_query: str = ""  # For debugging/transparency
    execution_time_ms: float = 0.0
    error: str | None = None


class StructuredKGDetector:
    """
    Detects if a query is suitable for direct Cypher execution.
    Uses pattern matching first (fast), with optional LLM fallback for ambiguous cases.
    """

    # Regex patterns for common structured queries (case-insensitive)
    # Format: (pattern, query_type, optional_filter_extraction)
    PATTERNS: list[tuple[str, StructuredQueryType]] = [
        # Document queries
        (r"^(list|show|get|display)\s+(all\s+)?(the\s+)?documents?$", StructuredQueryType.LIST_DOCUMENTS),
        (r"^(list|show|get)\s+(all\s+)?(the\s+)?documents?\s+(in|from)\s+", StructuredQueryType.LIST_DOCUMENTS),
        (r"^what\s+(documents?|files?)\s+(do\s+)?(we\s+|i\s+)?have", StructuredQueryType.LIST_DOCUMENTS),
        (r"^how many\s+(documents?|files?)", StructuredQueryType.COUNT_DOCUMENTS),
        (r"^count\s+(all\s+)?(documents?|files?)", StructuredQueryType.COUNT_DOCUMENTS),
        (r"^(what\'?s|what is)\s+the\s+(document|file)\s+count", StructuredQueryType.COUNT_DOCUMENTS),

        # Entity queries
        (r"^(list|show|get|display)\s+(all\s+)?(the\s+)?entities", StructuredQueryType.LIST_ENTITIES),
        (r"^what\s+entities\s+(do\s+)?(we\s+|i\s+)?have", StructuredQueryType.LIST_ENTITIES),
        (r"^how many\s+entities", StructuredQueryType.COUNT_ENTITIES),
        (r"^count\s+(all\s+)?entities", StructuredQueryType.COUNT_ENTITIES),
        (r"^(list|show)\s+(all\s+)?entity\s+types?", StructuredQueryType.LIST_ENTITY_TYPES),
        (r"^what\s+(types?\s+of\s+)?entities\s+exist", StructuredQueryType.LIST_ENTITY_TYPES),

        # Relationship queries
        (r"^(list|show|get)\s+(all\s+)?(the\s+)?relationships?", StructuredQueryType.LIST_RELATIONSHIPS),
        (r"^what\s+relationships?\s+(do\s+)?(we\s+|i\s+)?have", StructuredQueryType.LIST_RELATIONSHIPS),

        # Chunk queries
        (r"^how many\s+chunks?", StructuredQueryType.COUNT_CHUNKS),
        (r"^count\s+(all\s+)?chunks?", StructuredQueryType.COUNT_CHUNKS),

        # Stats queries
        (r"^(show|get|display)\s+(database|db|knowledge\s+base)?\s*stats?", StructuredQueryType.DOCUMENT_STATS),
        (r"^(what\'?s|what is)\s+the\s+(database|db)\s+status", StructuredQueryType.DOCUMENT_STATS),
    ]

    def detect(self, query: str) -> StructuredIntent:
        """
        Detect if a query is structured and extract intent.

        Args:
            query: The user's natural language query

        Returns:
            StructuredIntent with detected query type and any extracted filters
        """
        normalized = query.strip().lower()

        for pattern, query_type in self.PATTERNS:
            if re.match(pattern, normalized, re.IGNORECASE):
                logger.debug(f"Detected structured query: {query_type.value}")
                return StructuredIntent(
                    query_type=query_type,
                    original_query=query,
                    limit=50,
                )

        # No match - not a structured query
        return StructuredIntent(
            query_type=StructuredQueryType.NOT_STRUCTURED,
            original_query=query,
        )

    def is_structured(self, query: str) -> bool:
        """Quick check if query is structured."""
        return self.detect(query).query_type != StructuredQueryType.NOT_STRUCTURED


class CypherGenerator:
    """Generates safe, parameterized Cypher queries for structured intents."""

    # Cypher templates - all use parameters to prevent injection
    TEMPLATES: dict[StructuredQueryType, str] = {
        StructuredQueryType.LIST_DOCUMENTS: """
            MATCH (d:Document)
            WHERE d.tenant_id = $tenant_id
            RETURN d.id as id, d.filename as filename, d.status as status,
                   d.domain as domain, d.created_at as created_at
            ORDER BY d.created_at DESC
            LIMIT $limit
        """,

        StructuredQueryType.COUNT_DOCUMENTS: """
            MATCH (d:Document)
            WHERE d.tenant_id = $tenant_id
            RETURN count(d) as count
        """,

        StructuredQueryType.LIST_ENTITIES: """
            MATCH (e:Entity)
            WHERE e.tenant_id = $tenant_id
            RETURN e.id as id, e.name as name, e.type as type,
                   e.description as description
            ORDER BY e.name
            LIMIT $limit
        """,

        StructuredQueryType.COUNT_ENTITIES: """
            MATCH (e:Entity)
            WHERE e.tenant_id = $tenant_id
            RETURN count(e) as count
        """,

        StructuredQueryType.LIST_ENTITY_TYPES: """
            MATCH (e:Entity)
            WHERE e.tenant_id = $tenant_id
            RETURN DISTINCT e.type as type, count(e) as count
            ORDER BY count DESC
        """,

        StructuredQueryType.LIST_RELATIONSHIPS: """
            MATCH (e1:Entity)-[r]->(e2:Entity)
            WHERE e1.tenant_id = $tenant_id
              AND NOT type(r) IN ['BELONGS_TO', 'PARENT_OF', 'MENTIONS']
            RETURN e1.name as source, type(r) as relationship, e2.name as target,
                   r.description as description
            LIMIT $limit
        """,

        StructuredQueryType.COUNT_CHUNKS: """
            MATCH (c:Chunk)
            WHERE c.tenant_id = $tenant_id
            RETURN count(c) as count
        """,

        StructuredQueryType.DOCUMENT_STATS: """
            MATCH (d:Document {tenant_id: $tenant_id})
            WITH count(d) as docs
            OPTIONAL MATCH (c:Chunk {tenant_id: $tenant_id})
            WITH docs, count(c) as chunks
            OPTIONAL MATCH (e:Entity {tenant_id: $tenant_id})
            RETURN docs as document_count, chunks as chunk_count, count(e) as entity_count
        """,
    }

    def generate(self, intent: StructuredIntent, tenant_id: str) -> tuple[str, dict]:
        """
        Generate a Cypher query from an intent.

        Args:
            intent: The parsed structured intent
            tenant_id: Tenant ID for filtering

        Returns:
            Tuple of (cypher_query, parameters)
        """
        template = self.TEMPLATES.get(intent.query_type)
        if not template:
            raise ValueError(f"No template for query type: {intent.query_type}")

        params = {
            "tenant_id": tenant_id,
            "limit": intent.limit,
            "offset": intent.offset,
        }

        # Add any additional filters from intent
        params.update(intent.filters)

        return template.strip(), params


class StructuredQueryExecutor:
    """
    Orchestrates structured query detection and execution.
    """

    def __init__(self):
        self.detector = StructuredKGDetector()
        self.generator = CypherGenerator()

    async def try_execute(
        self,
        query: str,
        tenant_id: str
    ) -> StructuredResult | None:
        """
        Attempt to execute a query as a structured query.

        Returns None if the query is not suitable for structured execution.

        Args:
            query: User's natural language query
            tenant_id: Tenant context

        Returns:
            StructuredResult if executed, None if not a structured query
        """
        import time

        # Step 1: Detect if structured
        intent = self.detector.detect(query)

        if intent.query_type == StructuredQueryType.NOT_STRUCTURED:
            return None

        # Step 2: Generate Cypher
        try:
            cypher_query, params = self.generator.generate(intent, tenant_id)
        except ValueError as e:
            logger.error(f"Failed to generate Cypher: {e}")
            return None

        # Step 3: Execute
        start_time = time.time()

        try:
            # Ensure Neo4j is connected
            await neo4j_client.connect()

            results = await neo4j_client.execute_read(cypher_query, params)

            execution_time_ms = (time.time() - start_time) * 1000

            # Determine count based on query type
            if intent.query_type in [
                StructuredQueryType.COUNT_DOCUMENTS,
                StructuredQueryType.COUNT_ENTITIES,
                StructuredQueryType.COUNT_CHUNKS,
            ]:
                count = results[0].get("count", 0) if results else 0
                data = [{"count": count}]
            else:
                data = results
                count = len(results)

            logger.info(
                f"Structured query executed: {intent.query_type.value} "
                f"returned {count} results in {execution_time_ms:.1f}ms"
            )

            return StructuredResult(
                success=True,
                query_type=intent.query_type,
                data=data,
                count=count,
                cypher_query=cypher_query,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.error(f"Structured query execution failed: {e}")
            return StructuredResult(
                success=False,
                query_type=intent.query_type,
                error=str(e),
                cypher_query=cypher_query,
                execution_time_ms=(time.time() - start_time) * 1000,
            )


# Global executor instance
structured_executor = StructuredQueryExecutor()
