"""
Query API Routes
================

Endpoints for querying the knowledge base.
Phase 2: Baseline RAG implementation with vector retrieval and LLM generation.
"""

import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.api.config import settings
from src.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    Source,
    StructuredQueryResponse,
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
            from src.core.metrics.collector import MetricsCollector
            from src.core.services.generation import GenerationService
            from src.core.services.retrieval import RetrievalConfig, RetrievalService

            providers = getattr(settings, "providers", None)
            openai_key = getattr(providers, "openai_api_key", None) or settings.openai_api_key
            anthropic_key = getattr(providers, "anthropic_api_key", None) or settings.anthropic_api_key

            # Check if API keys are configured
            if not openai_key and not anthropic_key:
                logger.warning("No LLM API keys configured - RAG pipeline will fail")

            retrieval_config = RetrievalConfig(
                milvus_host=settings.db.milvus_host,
                milvus_port=settings.db.milvus_port,
            )

            _retrieval_service = RetrievalService(
                openai_api_key=openai_key or None,
                anthropic_api_key=anthropic_key or None,
                redis_url=settings.db.redis_url,
                config=retrieval_config,
            )

            _generation_service = GenerationService(
                openai_api_key=openai_key or None,
                anthropic_api_key=anthropic_key or None,
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
    status_code=status.HTTP_200_OK,
    summary="Query the Knowledge Base",
    description="""
    Submit a natural language query to retrieve relevant information
    from the knowledge base.

    **Phase 2 Implementation**: Vector retrieval with LLM answer generation.
    - Embeds query and searches Milvus for relevant chunks
    - Reranks results using FlashRank
    - Generates answer with citations using LLM

    **Structured Queries**: List/count queries are executed directly via Cypher
    for instant responses without LLM generation.
    """,
    responses={
        200: {
            "description": "Query response (can be QueryResponse or StructuredQueryResponse)",
            "content": {
                "application/json": {
                    "examples": {
                        "rag_response": {
                            "summary": "RAG Response",
                            "value": {"answer": "...", "sources": [], "timing": {}}
                        },
                        "structured_response": {
                            "summary": "Structured Query Response",
                            "value": {"query_type": "list_documents", "data": [], "count": 0}
                        }
                    }
                }
            }
        }
    },
)
async def query(request: QueryRequest, http_request: Request) -> QueryResponse | StructuredQueryResponse:
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

    # =========================================================================
    # STRUCTURED QUERY CHECK - Bypass RAG for list/count queries
    # =========================================================================
    try:
        from src.core.query.structured_query import structured_executor

        structured_result = await structured_executor.try_execute(
            query=request.query,
            tenant_id=tenant_id,
        )

        if structured_result and structured_result.success:
            # Return structured response (no LLM, no RAG)
            logger.info(
                f"Structured query executed: {structured_result.query_type.value} "
                f"in {structured_result.execution_time_ms:.1f}ms"
            )

            # Generate human-readable message
            count = structured_result.count
            query_type = structured_result.query_type.value
            if "count" in query_type:
                message = f"Found {count} {query_type.replace('count_', '').replace('_', ' ')}"
            else:
                message = f"Retrieved {count} {query_type.replace('list_', '').replace('_', ' ')}"

            return StructuredQueryResponse(
                query_type=query_type,
                data=structured_result.data,
                count=count,
                timing=TimingInfo(
                    total_ms=round(structured_result.execution_time_ms, 2),
                    retrieval_ms=round(structured_result.execution_time_ms, 2),
                    generation_ms=0,
                ),
                message=message,
            )

    except Exception as e:
        # If structured query fails, fall through to RAG pipeline
        logger.debug(f"Structured query check failed, using RAG: {e}")

    try:
        retrieval_service, generation_service, metrics = _get_services()
    except Exception as e:
        # Fallback to no-op response if services unavailable
        logger.error(f"Services unavailable: {e}")
        return _fallback_response(request, start_time, str(e))
    
    # =========================================================================
    # AGENTIC MODE (Phase 1)
    # =========================================================================
    if request.options and request.options.agent_mode:
        try:
            from src.core.agent.orchestrator import AgentOrchestrator
            from src.core.agent.prompts import AGENT_SYSTEM_PROMPT
            from src.core.tools.retrieval import create_retrieval_tool
            from src.core.tools.filesystem import create_filesystem_tools
            
            # Initialize Tools
            # Initialize Tools
            retrieval_tool_def = create_retrieval_tool(retrieval_service, tenant_id)
            
            tool_map = {
                retrieval_tool_def["name"]: retrieval_tool_def["func"]
            }
            tool_schemas = [retrieval_tool_def["schema"]]

            agent_role = request.options.agent_role
            
            # Role-Specific Tools
            if agent_role == "maintainer":
                 # Maintainer: Full filesystem access
                fs_tools = create_filesystem_tools(base_path=".") 
                for t in fs_tools:
                    tool_map[t["name"]] = t["func"]
                    tool_schemas.append(t["schema"])
            else:
                 # Knowledge (Default): RAG + Graph only
                 from src.core.tools.graph import GRAPH_TOOLS, query_graph
                 
                 # Add Graph Tool
                 tool_map["query_graph"] = query_graph
                 tool_schemas.extend(GRAPH_TOOLS)
                 
                 # Note: We do NOT load filesystem tools here.
            
            # Initialize Agent
            agent = AgentOrchestrator(
                generation_service=generation_service,
                tools=tool_map,
                tool_schemas=tool_schemas,
                system_prompt=AGENT_SYSTEM_PROMPT
            )
            
            # Run Agent
            agent_response = await agent.run(
                query=request.query,
                conversation_id=request.conversation_id
            )
            
            # Fill in timing info (approximate)
            total_ms = (time.perf_counter() - start_time) * 1000
            agent_response.timing.total_ms = round(total_ms, 2)
            
            return agent_response
            
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            # Fallback to standard RAG if agent crashes
            pass

    # Generate query ID for tracking
    from src.shared.identifiers import generate_query_id
    query_id = generate_query_id()

    try:
        # Track metrics
        async with metrics.track_query(query_id, tenant_id, request.query) as query_metrics:
            query_metrics.conversation_id = request.conversation_id or query_id

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
                query_metrics.input_tokens = gen_result.input_tokens
                query_metrics.output_tokens = gen_result.output_tokens
                query_metrics.cost_estimate = gen_result.cost_estimate
                query_metrics.model = gen_result.model
                query_metrics.provider = gen_result.provider
                query_metrics.sources_cited = len(gen_result.sources)
                query_metrics.answer_length = len(answer)
                # Set operation type and response for tracking
                query_metrics.operation = "rag_query"
                query_metrics.response = answer[:500] if len(answer) > 500 else answer

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
        # Note: metrics context manager auto-closes, but we need to mark failure if possible.
        # Ideally, we should have access to query_metrics here, but it's scoped to the try block.
        # Best practice: move try/except INSIDE the metrics context manager or handle it better.
        # For now, we will rely on successful queries for most stats, but let's try to capture error if we can.
        # Actually, since track_query is a context manager, if we want to capture exception, we should suppression=False
        # and handle it in __aexit__.
        # Let's modify collector.py's QueryTracker.__aexit__ to capture exception?
        # A simpler way is to wrap the inner logic in try/except and set error on metrics.
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


@router.api_route(
    "/stream",
    methods=["GET", "POST"],
    summary="Stream Query Response",
    description="Stream the query response using Server-Sent Events.",
)
async def query_stream(
    http_request: Request,
    request: QueryRequest = None,
    query: str = None,
):
    """
    Stream the query response.

    Uses SSE to stream LLM tokens as they're generated.
    Supports both POST (JSON body) and GET (query params).
    """
    # Handle GET request parameters
    if http_request.method == "GET":
        if not query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query parameter 'query' is required for GET requests",
            )
        request = QueryRequest(query=query)

    # Handle POST request body (FastAPI dependency injection)
    if request is None and http_request.method == "POST":
         # This case should be handled by FastAPI if signature is correct,
         # but since we made request optional for GET, we might need to validate.
         # Actually, mixing Body and Query params in one function can be tricky in FastAPI.
         # Better approach is to separate into two functions or use logic below.
         pass

    if request is None:
         # If dependency failed or wasn't provided (shouldn't happen for POST if validated)
         raise HTTPException(status_code=400, detail="Invalid request")

    tenant_id = _get_tenant_id(http_request)
    logger.info(f"SSE stream request: query={request.query[:50]}..., tenant={tenant_id}")

    try:
        retrieval_service, generation_service, _ = _get_services()
        logger.info("SSE: Services loaded successfully")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"RAG services unavailable: {e}",
        ) from e

    async def generate_stream():
        """Generate SSE stream."""
        logger.info("SSE: Generator started")
        # Yield immediately so client knows connection is alive
        yield f"event: status\ndata: {json.dumps('Searching documents...')}\n\n"

        try:
            # First, retrieve relevant chunks
            document_ids = request.filters.document_ids if request.filters else None
            max_chunks = request.options.max_chunks if request.options else 10

            # Add timeout to prevent hangs
            import asyncio
            try:
                retrieval_result = await asyncio.wait_for(
                    retrieval_service.retrieve(
                        query=request.query,
                        tenant_id=tenant_id,
                        document_ids=document_ids,
                        top_k=max_chunks,
                    ),
                    timeout=35.0
                )
            except TimeoutError:
                logger.warning("Retrieval timed out after 35 seconds")
                yield f"event: error\ndata: {json.dumps('Document retrieval timed out. Please try again.')}\n\n"
                return

            if not retrieval_result.chunks:
                yield f"data: {json.dumps('No relevant documents found.')}\n\n"
                return


            # Stream the answer
            full_answer = ""
            async for event_dict in generation_service.generate_stream(
                query=request.query,
                candidates=retrieval_result.chunks,
                conversation_history=None,
            ):
                event = event_dict.get("event", "message")
                data = event_dict.get("data", "")
                
                # Accumulate answer for history
                if event == "token":
                    full_answer += str(data)

                # ALWAYS JSON encode data to preserve newlines and special chars
                data_str = json.dumps(data)

                yield f"event: {event}\ndata: {data_str}\n\n"

            # SAVE INTERACTION TO HISTORY
            try:
                # Truncate for summary
                summary_text = full_answer[:200] + "..." if len(full_answer) > 200 else full_answer
                title_text = request.query[:50] + "..." if len(request.query) > 50 else request.query
                
                import uuid
                from src.core.models.memory import ConversationSummary
                from src.api.deps import _async_session_maker
                
                async with _async_session_maker() as session:
                    new_summary = ConversationSummary(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        user_id="user", # Default user
                        title=title_text,
                        summary=summary_text,
                        metadata_={
                            "query": request.query,
                            "answer": full_answer,
                            "model": request.options.model if request.options else "default"
                        }
                    )
                    session.add(new_summary)
                    await session.commit()
                    logger.info(f"Saved conversation history: {new_summary.id}")
                    
            except Exception as e:
                logger.error(f"Failed to save conversation history: {e}")
                    


            yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"

        except Exception as e:
            logger.exception(f"Stream generation failed: {e}")
            yield f"event: error\ndata: {json.dumps(str(e))}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
