"""
Shared Query Models
===================

Request and response models for the query system, used by both API and Core.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    """Available search strategies."""

    BASIC = "basic"         # Vector search only
    LOCAL = "local"         # Entity-focused graph traversal
    GLOBAL = "global"       # Map-reduce over community summaries
    DRIFT = "drift"         # Dynamic reasoning and exploration
    STRUCTURED = "structured"  # Direct Cypher for list/count queries


class DateRange(BaseModel):
    """Date range filter for queries."""

    start: datetime | None = Field(None, description="Start of date range")
    end: datetime | None = Field(None, description="End of date range")


class QueryFilters(BaseModel):
    """Filters to narrow query scope."""

    document_ids: list[str] | None = Field(
        None,
        description="Limit search to specific documents",
    )
    date_range: DateRange | None = Field(
        None,
        description="Filter by document date range",
    )
    tags: list[str] | None = Field(
        None,
        description="Filter by document tags",
    )


class QueryOptions(BaseModel):
    """Options controlling query behavior."""

    search_mode: SearchMode = Field(
        SearchMode.BASIC,
        description="Search strategy to use (default: basic)",
    )
    use_hyde: bool = Field(
        False,
        description="Use Hypothetical Document Embeddings",
    )
    use_rewrite: bool = Field(
        True,
        description="Enable query rewriting for better context resolution",
    )
    use_decomposition: bool = Field(
        False,
        description="Enable query decomposition for complex questions",
    )
    include_trace: bool = Field(
        False,
        description="Include execution trace in response",
    )
    max_chunks: int = Field(
        10,
        ge=1,
        le=50,
        description="Maximum chunks to retrieve",
    )
    traversal_depth: int = Field(
        2,
        ge=0,
        le=5,
        description="Graph traversal depth for entity expansion",
    )
    include_sources: bool = Field(
        True,
        description="Include source citations in response",
    )
    stream: bool = Field(
        False,
        description="Stream response tokens (SSE)",
    )
    agent_mode: bool = Field(
        False,
        description="Enable Agentic RAG mode (loop + tools)",
    )
    agent_role: str = Field(
        "knowledge",
        description="Agent role: 'knowledge' (default, RAG tools only) or 'maintainer' (filesystem access)",
        pattern="^(knowledge|maintainer)$"
    )
    model: str | None = Field(
        None,
        description="Override LLM model for generation (e.g. gpt-5-nano)",
    )


class QueryRequest(BaseModel):
    """Query request payload."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The question or query to answer",
    )
    filters: QueryFilters | None = Field(
        None,
        description="Optional filters to narrow scope",
    )
    options: QueryOptions | None = Field(
        None,
        description="Query execution options",
    )
    conversation_id: str | None = Field(
        None,
        description="Conversation ID for multi-turn context",
    )


class Source(BaseModel):
    """A source citation for an answer."""

    chunk_id: str = Field(..., description="Chunk identifier")
    document_id: str = Field(..., description="Parent document identifier")
    document_name: str | None = Field(None, description="Document filename")
    text: str = Field(..., description="Relevant text excerpt")
    score: float = Field(..., description="Relevance score (0-1)")
    page: int | None = Field(None, description="Page number if applicable")


class TraceStep(BaseModel):
    """A single step in the query execution trace."""

    step: str = Field(..., description="Step name")
    duration_ms: float | None = Field(0.0, description="Step duration in milliseconds")
    details: dict[str, Any] | None = Field(None, description="Step-specific details")


class TimingInfo(BaseModel):
    """Timing breakdown for the query."""

    total_ms: float = Field(..., description="Total query time in milliseconds")
    analysis_ms: float | None = Field(None, description="Query analysis and routing time")
    retrieval_ms: float | None = Field(None, description="Retrieval phase time")
    reranking_ms: float | None = Field(None, description="Reranking phase time")
    generation_ms: float | None = Field(None, description="Generation phase time")


class QueryResponse(BaseModel):
    """Query response payload."""

    answer: str = Field(..., description="Generated answer")
    sources: list[Source] = Field(
        default_factory=list,
        description="Source citations",
    )
    trace: list[TraceStep] | None = Field(
        None,
        description="Execution trace (if requested)",
    )
    timing: TimingInfo = Field(..., description="Timing information")
    conversation_id: str | None = Field(
        None,
        description="Conversation ID for follow-up queries",
    )
    follow_up_questions: list[str] | None = Field(
        None,
        description="Suggested follow-up questions",
    )


class StructuredQueryResponse(BaseModel):
    """Response for structured queries (list, count, aggregates)."""

    query_type: str = Field(..., description="Type of structured query executed")
    data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tabular result data",
    )
    count: int = Field(..., description="Number of results")
    timing: TimingInfo = Field(..., description="Timing information")
    message: str | None = Field(
        None,
        description="Human-readable summary of results",
    )
