"""
Query API Routes
================

Endpoints for querying the knowledge base.
Phase 2: Baseline RAG implementation with vector retrieval and LLM generation.
"""

import logging
import time
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.api.config import settings
from src.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    Source,
    TimingInfo,
    TraceStep,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

# =============================================================================
# Service Dependencies
# =============================================================================

# Lazy-loaded services to avoid import errors if dependencies missing
_retrieval_service = None
_generation_service = None
_metrics_collector = None


def _get_services():
    """Get or initialize RAG services."""
    global _retrieval_service, _generation_service, _metrics_collector

    if _retrieval_service is None:
        try:
            from src.core.services.retrieval import RetrievalService, RetrievalConfig
            from src.core.services.generation import GenerationService, GenerationConfig
            from src.core.metrics.collector import MetricsCollector

            # Check if API keys are configured
            if not settings.openai_api_key and not settings.anthropic_api_key:
                logger.warning("No LLM API keys configured - RAG pipeline will fail")

            retrieval_config = RetrievalConfig(
                milvus_host=settings.db.milvus_host,
                milvus_port=settings.db.milvus_port,
            )

            _retrieval_service = RetrievalService(
                openai_api_key=settings.openai_api_key or None,
                anthropic_api_key=settings.anthropic_api_key or None,
                redis_url=settings.db.redis_url,
                config=retrieval_config,
            )

            _generation_service = GenerationService(
                openai_api_key=settings.openai_api_key or None,
                anthropic_api_key=settings.anthropic_api_key or None,
            )

            _metrics_collector = MetricsCollector(
                redis_url=settings.db.redis_url,
            )

            logger.info("RAG services initialized successfully")

        except ImportError as e:
            logger.error(f"Failed to import RAG services: {e}")
            raise

        except Exception as e:
            logger.error(f"Failed to initialize RAG services: {e}")
            raise

    return _retrieval_service, _generation_service, _metrics_collector


def _get_tenant_id(request: Request) -> str:
    """Extract tenant ID from request context."""
    # Check if set by auth middleware
    if hasattr(request.state, "tenant_id"):
        return request.state.tenant_id
    return settings.tenant_id


# =============================================================================
# Query Endpoint
# =============================================================================


@router.post(
    "",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Query the Knowledge Base",
    description="""
    Submit a natural language query to retrieve relevant information
    from the knowledge base.

    **Phase 2 Implementation**: Vector retrieval with LLM answer generation.
    - Embeds query and searches Milvus for relevant chunks
    - Reranks results using FlashRank
    - Generates answer with citations using LLM
    """,
)
async def query(request: QueryRequest, http_request: Request) -> QueryResponse:
    """
    Query the knowledge base.

    Executes the full RAG pipeline:
    1. Embed query (with caching)
    2. Vector search in Milvus
    3. Rerank results
    4. Generate answer with LLM
    5. Return answer with citations and timing

    Args:
        request: Query request with question and options
        http_request: FastAPI request for context

    Returns:
        QueryResponse: Answer with sources and timing
    """
    start_time = time.perf_counter()
    tenant_id = _get_tenant_id(http_request)
    include_trace = request.options.include_trace if request.options else False
    max_chunks = request.options.max_chunks if request.options else 10

    trace_steps: list[TraceStep] = []

    try:
        retrieval_service, generation_service, metrics = _get_services()
    except Exception as e:
        # Fallback to no-op response if services unavailable
        logger.error(f"Services unavailable: {e}")
        return _fallback_response(request, start_time, str(e))

    # Generate query ID for tracking
    from src.shared.identifiers import generate_query_id
    query_id = generate_query_id()

    try:
        # Track metrics
        async with metrics.track_query(query_id, tenant_id, request.query) as query_metrics:
            # Step 1: Parse query
            step_start = time.perf_counter()
            trace_steps.append(TraceStep(
                step="parse_query",
                duration_ms=(time.perf_counter() - step_start) * 1000,
                details={"query_length": len(request.query), "query_id": query_id},
            ))

            # Step 2: Retrieval (embedding + search + rerank)
            step_start = time.perf_counter()
            document_ids = request.filters.document_ids if request.filters else None

            retrieval_result = await retrieval_service.retrieve(
                query=request.query,
                tenant_id=tenant_id,
                document_ids=document_ids,
                top_k=max_chunks,
                include_trace=include_trace,
                options=request.options,
                history=None,  # Placeholder until conversation service is implemented
            )

            retrieval_ms = (time.perf_counter() - step_start) * 1000
            query_metrics.retrieval_latency_ms = retrieval_ms
            query_metrics.chunks_retrieved = len(retrieval_result.chunks)
            query_metrics.cache_hit = retrieval_result.cache_hit

            # Add retrieval trace steps
            for rt in retrieval_result.trace:
                trace_steps.append(TraceStep(
                    step=rt["step"],
                    duration_ms=rt.get("duration_ms", 0),
                    details={k: v for k, v in rt.items() if k not in ("step", "duration_ms")},
                ))

            # Step 3: Generation
            step_start = time.perf_counter()

            if not retrieval_result.chunks:
                # No relevant chunks found
                answer = (
                    "I couldn't find any relevant information in the knowledge base "
                    f"to answer: \"{request.query[:100]}...\"\n\n"
                    "This could mean:\n"
                    "- No documents have been uploaded yet\n"
                    "- The query doesn't match available content\n"
                    "- Try rephrasing your question"
                )
                sources: list[Source] = []
                follow_ups = ["What documents are available?", "How do I upload documents?"]
            else:
                # Generate answer from chunks
                gen_result = await generation_service.generate(
                    query=request.query,
                    candidates=retrieval_result.chunks,
                    include_trace=include_trace,
                )

                answer = gen_result.answer
                query_metrics.tokens_used = gen_result.tokens_used
                query_metrics.cost_estimate = gen_result.cost_estimate
                query_metrics.model = gen_result.model
                query_metrics.sources_cited = len(gen_result.sources)
                query_metrics.answer_length = len(answer)

                # Build source citations
                sources = [
                    Source(
                        chunk_id=s.chunk_id,
                        document_id=s.document_id,
                        document_name=s.title,
                        text=s.content_preview,
                        score=s.score,
                        page=None,
                    )
                    for s in gen_result.sources
                ]

                follow_ups = gen_result.follow_up_questions

                # Add generation trace
                for gt in gen_result.trace:
                    trace_steps.append(TraceStep(
                        step=gt["step"],
                        duration_ms=gt.get("duration_ms", 0),
                        details={k: v for k, v in gt.items() if k not in ("step", "duration_ms")},
                    ))

            generation_ms = (time.perf_counter() - step_start) * 1000
            query_metrics.generation_latency_ms = generation_ms

        # Calculate total time
        total_ms = (time.perf_counter() - start_time) * 1000

        return QueryResponse(
            answer=answer,
            sources=sources if (request.options and request.options.include_sources) else [],
            trace=trace_steps if include_trace else None,
            timing=TimingInfo(
                total_ms=round(total_ms, 2),
                retrieval_ms=round(retrieval_ms, 2),
                generation_ms=round(generation_ms, 2),
            ),
            conversation_id=request.conversation_id or query_id,
            follow_up_questions=follow_ups,
        )

    except Exception as e:
        logger.exception(f"Query failed: {e}")
        return _fallback_response(request, start_time, str(e))


def _fallback_response(
    request: QueryRequest,
    start_time: float,
    error: str,
) -> QueryResponse:
    """Generate a fallback response when services fail."""
    elapsed = (time.perf_counter() - start_time) * 1000

    return QueryResponse(
        answer=(
            f"I'm unable to process your query at the moment. "
            f"Error: {error}\n\n"
            f"Your query: \"{request.query[:100]}{'...' if len(request.query) > 100 else ''}\""
        ),
        sources=[],
        trace=None,
        timing=TimingInfo(
            total_ms=round(elapsed, 2),
            retrieval_ms=None,
            generation_ms=None,
        ),
        conversation_id=request.conversation_id,
        follow_up_questions=[
            "Please check that the system is properly configured",
            "Ensure API keys are set in the environment",
        ],
    )


# =============================================================================
# Streaming Endpoint
# =============================================================================


@router.post(
    "/stream",
    summary="Stream Query Response",
    description="Stream the query response using Server-Sent Events.",
)
async def query_stream(request: QueryRequest, http_request: Request):
    """
    Stream the query response.

    Uses SSE to stream LLM tokens as they're generated.
    """
    tenant_id = _get_tenant_id(http_request)

    try:
        retrieval_service, generation_service, _ = _get_services()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"RAG services unavailable: {e}",
        )

    async def generate_stream():
        """Generate SSE stream."""
        try:
            # First, retrieve relevant chunks
            document_ids = request.filters.document_ids if request.filters else None
            max_chunks = request.options.max_chunks if request.options else 10

            retrieval_result = await retrieval_service.retrieve(
                query=request.query,
                tenant_id=tenant_id,
                document_ids=document_ids,
                top_k=max_chunks,
            )

            if not retrieval_result.chunks:
                yield "data: No relevant documents found.\n\n"
                return

            # Stream the answer
            async for event_dict in generation_service.generate_stream(
                query=request.query,
                candidates=retrieval_result.chunks,
                conversation_history=None,
            ):
                event = event_dict.get("event", "message")
                data = event_dict.get("data", "")
                
                if isinstance(data, (dict, list)):
                    data_str = json.dumps(data)
                else:
                    data_str = str(data)
                
                yield f"event: {event}\ndata: {data_str}\n\n"

            yield "event: done\ndata: [DONE]\n\n"

        except Exception as e:
            logger.exception(f"Stream generation failed: {e}")
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
