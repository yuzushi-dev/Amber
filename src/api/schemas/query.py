"""
Query Schemas
=============

Request and response models for the query API.
"""

from pydantic import BaseModel, Field

from src.shared.kernel.models.query import (
    DateRange,
    QueryFilters,
    QueryOptions,
    QueryResponse,
    SearchMode,
    Source,
    StructuredQueryResponse,
    TimingInfo,
    TraceStep,
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

    model_config = {"json_schema_extra": {"example": {
        "query": "What are the main features of the GraphRAG system?",
        "options": {"include_trace": True, "max_chunks": 5},
    }}}

