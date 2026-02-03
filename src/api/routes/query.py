"""
Query API Routes
================

Endpoints for querying the knowledge base.
Phase 2: Baseline RAG implementation with vector retrieval and LLM generation.
"""

import json
import re
import logging
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import get_db_session

from src.api.config import settings
from src.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    Source,
    StructuredQueryResponse,
    TimingInfo,
    TraceStep,
)
from src.core.generation.domain.provider_models import (
    ProviderError,
    QuotaExceededError,
    RateLimitError
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

# =============================================================================
# Service Dependencies
# =============================================================================




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
async def query(
    request: QueryRequest, 
    http_request: Request,
    session: AsyncSession = Depends(get_db_session)
) -> QueryResponse | StructuredQueryResponse:
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
    from src.core.retrieval.application.use_cases_query import QueryUseCase
    from src.amber_platform.composition_root import (
        build_retrieval_service,
        build_generation_service,
        build_metrics_collector,
    )

    tenant_id = _get_tenant_id(http_request)
    
    # Instantiate Use Case using Composition Root factories
    try:
        use_case = QueryUseCase(
            retrieval_service=build_retrieval_service(session),
            generation_service=build_generation_service(session),
            metrics_collector=build_metrics_collector(),
        )
        
        # Determine User ID (extract logic from previous implementation)
        user_id = http_request.headers.get("X-User-ID", "default_user")

        return await use_case.execute(
            request=request,
            tenant_id=tenant_id,
            http_request_state=http_request.state,
            user_id=user_id,
        )

    except Exception as e:
        start_time = time.perf_counter() # Fallback Start Time
        logger.error(f"Query execution failed: {e}")
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


async def _query_stream_impl(
    http_request: Request,
    request: QueryRequest = None,
    query: str = None,
    agent_mode: bool = False,
    model: str = None,  # Added model parameter
    conversation_id: str = None,  # Added for threading support
    session: AsyncSession = None,
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
        
        from src.api.schemas.query import QueryOptions
        request = QueryRequest(
            query=query,
            options=QueryOptions(agent_mode=agent_mode, model=model),
            conversation_id=conversation_id  # Pass through for threading
        )

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
        from src.amber_platform.composition_root import build_retrieval_service, build_generation_service
        retrieval_service = build_retrieval_service(session)
        generation_service = build_generation_service(session)
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
        # Add 4KB padding to force Nginx/Proxy buffer flush (even with compression)
        padding_token = "abcdefghijklmnopqrstuvwxyz1234567890!@#$%^&*()_+[]{};'.,<>?"
        yield f": {(padding_token * 100)[:4096]}\n\n"
        yield f"event: status\ndata: {json.dumps('Searching documents...')}\n\n"

        # =========================================================================
        # STICKY MODE CHECK
        # =========================================================================
        # Check if this is a continuation of an AGENT conversation
        if request.conversation_id and not (request.options and request.options.agent_mode):
            try:
                from src.core.generation.domain.memory_models import ConversationSummary
                from src.api.deps import _get_async_session_maker
                
                async with _get_async_session_maker()() as session:
                    existing_conv = await session.get(ConversationSummary, request.conversation_id)
                    if existing_conv and existing_conv.metadata_:
                        mode = existing_conv.metadata_.get("mode")
                        if mode == "agent":
                            logger.info(f"Auto-switching conversation {request.conversation_id} to Agent Mode (Sticky)")
                            if not request.options:
                                from src.api.schemas.query import QueryOptions
                                request.options = QueryOptions(agent_mode=True)
                            else:
                                request.options.agent_mode = True
            except Exception as e:
                logger.warning(f"Failed to check stickiness: {e}")

        try:
            # =========================================================================
            # AGENTIC MODE SUPPORT
            # =========================================================================
            if request.options and request.options.agent_mode:
                yield f"event: status\ndata: {json.dumps('Consulting agent tools (Mail, Calendar, etc.)...')}\n\n"
                
                try:
                    # Determine ID upfront
                    import uuid
                    agent_conversation_id = request.conversation_id or str(uuid.uuid4())
                    # Emit availability immediately
                    logger.info(f"EMITTING Agent conversation_id SSE event upfront: {agent_conversation_id}")
                    yield f"event: conversation_id\ndata: {json.dumps(agent_conversation_id)}\n\n"

                    # Emit Routing Info
                    yield f"event: routing\ndata: {json.dumps({'categories': ['Agent Tools'], 'confidence': 1.0})}\n\n"

                    from src.core.generation.application.agent.orchestrator import AgentOrchestrator
                    from src.core.generation.application.agent.prompts import AGENT_SYSTEM_PROMPT
                    from src.core.tools.retrieval import create_retrieval_tool
                    from src.core.tools.filesystem import create_filesystem_tools
                    from src.core.tools.graph import GRAPH_TOOLS, query_graph
                    full_answer = agent_response.answer
                    summary_text = full_answer[:200] + "..." if len(full_answer) > 200 else full_answer
                    title_text = request.query[:50] + "..." if len(request.query) > 50 else request.query
                    
                    from datetime import datetime
                    from src.core.generation.domain.memory_models import ConversationSummary
                    from src.api.deps import _get_async_session_maker
                    
                    async with _get_async_session_maker()() as session:
                        # Try to find existing conversation
                        existing_summary = None
                        if request.conversation_id:
                            existing_summary = await session.get(ConversationSummary, agent_conversation_id)

                        if existing_summary:
                            # UPDATE existing conversation
                            # 1. Append to history in metadata
                            history = existing_summary.metadata_.get("history", [])
                            history.append({
                                "query": request.query, 
                                "answer": full_answer,
                                "sources": agent_response.sources if hasattr(agent_response, "sources") else [],
                                "timestamp": datetime.utcnow().isoformat()
                            })
                            existing_summary.metadata_["history"] = history
                            
                            # 2. Update top-level metadata to reflect LATEST turn
                            existing_summary.metadata_["query"] = request.query
                            existing_summary.metadata_["answer"] = full_answer
                            existing_summary.metadata_["sources"] = agent_response.sources if hasattr(agent_response, "sources") else []
                            existing_summary.metadata_["timestamp"] = datetime.utcnow().isoformat()
                            
                            # 3. Flag as modified for SQLAlchemy
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(existing_summary, "metadata_")
                            
                            session.add(existing_summary)
                            await session.commit()
                            logger.info(f"Updated AGENT conversation history: {existing_summary.id}")
                        else:
                            # INSERT new conversation
                            new_summary = ConversationSummary(
                                id=agent_conversation_id,
                                tenant_id=tenant_id,
                                user_id="user", # Default user
                                title=title_text,
                                summary=summary_text,
                                metadata_={
                                    "query": request.query,
                                    "answer": full_answer,
                                    "model": "agent-default",
                                    "mode": "agent",
                                    "tools_used": [
                                        t.get("function", {}).get("name", t.get("name", "unknown")) 
                                        for t in tool_schemas
                                    ],
                                    "history": [{
                                        "query": request.query, 
                                        "answer": full_answer,
                                        "sources": agent_response.sources if hasattr(agent_response, "sources") else [],
                                        "routing_info": {"categories": ["Agent Tools"], "confidence": 1.0},
                                        "timestamp": datetime.utcnow().isoformat()
                                    }]
                                }
                            )
                            session.add(new_summary)
                            await session.commit()
                            logger.info(f"Saved AGENT conversation history: {new_summary.id}")
                            


                    # Stream the result as tokens (AgentOrchestrator returns full answer currently)
                    # Preserve whitespace to keep formatting intact.
                    answer_text = agent_response.answer or ""
                    for chunk in re.findall(r"\S+|\s+", answer_text):
                        yield f"event: token\ndata: {json.dumps(chunk)}\n\n"
                    # Preserve compatibility for clients expecting a full message event.
                    yield f"event: message\ndata: {json.dumps(answer_text)}\n\n"

                    yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"
                    return

                except Exception as e:
                    logger.error(f"Agent stream failed: {e}")
                    yield f"event: error\ndata: {json.dumps(f'Agent error: {str(e)}')}\n\n"
                    return

            # STANDARD RAG PIPELINE
            # First, retrieve relevant chunks
            # Standard RAG Pipeline
            # First, retrieve relevant chunks
            document_ids = request.filters.document_ids if request.filters else None
            max_chunks = request.options.max_chunks if request.options else 10
            
            # Rate Limit Protection
            from src.core.admin_ops.application.tuning_service import TuningService
            from src.api.deps import _get_async_session_maker
            from src.shared.kernel.runtime import get_settings
            from src.core.generation.application.llm_model_resolver import resolve_tenant_llm_model
            from src.core.generation.infrastructure.providers.openai import OpenAILLMProvider
            
            try:
                # 1. Check explicit override
                effective_model = request.options.model if request.options else None
                
                # 2. If no override, fetch Tenant Config
                if not effective_model:
                    settings = get_settings()
                    tuning_service = TuningService(_get_async_session_maker())
                    tenant_config = await tuning_service.get_tenant_config(tenant_id)
                    effective_model, _ = resolve_tenant_llm_model(
                        tenant_config,
                        settings,
                        context="query.rate_limit_clamp",
                        tenant_id=tenant_id,
                    )
                    
                # Apply Clamp
                if effective_model:
                    model_cfg = OpenAILLMProvider.models.get(effective_model)
                    if model_cfg:
                        model_limit = model_cfg.get("max_top_k")
                        if model_limit and max_chunks > model_limit:
                            logger.warning(f"Clamping max_chunks from {max_chunks} to {model_limit} for model {effective_model}")
                            max_chunks = model_limit

            except Exception as e:
                logger.error(f"Failed to resolve effective model for rate limiting: {e}")

            # Add timeout to prevent hangs
            import asyncio
            import asyncio
            # Add specific error handling for retrieval to catch retry/rate limit errors early
            try:
                retrieval_result = await asyncio.wait_for(
                    retrieval_service.retrieve(
                        query=request.query,
                        tenant_id=tenant_id,
                        document_ids=document_ids,
                        top_k=max_chunks,
                    ),
                    timeout=60.0
                )
            except Exception as e:
                 # Re-raise to let the outer exception handler (the one we added for generation) catch it
                 # But wait, the outer handler is inside the stream generator loop? 
                 # No, we are currently in _query_stream_impl, which calls generation_service.generate_stream
                 # The error handling we added previously is INSIDE generation_service.generate_stream (or around it in the loop)
                 # We need to make sure THIS error is also caught and emitted as a proper SSE event
                 
                 # Actually, looking at the code structure:
                 # _query_stream_impl is an async generator.
                 # It has a big try...except block (lines 200..something)? No, let me check view_file 280 output.
                 # The view output shows lines 500-600.
                 # The retrieval is separate.
                 
                 # We should re-raise this in a way that our main exception handler catches it?
                 # OR we just handle it here similar to the generic handler we built.
                 
                 logger.error(f"Retrieval failed: {e}")
                 
                 logger.error(f"Retrieval failed: {e}")
                 
                 from src.shared.error_handling import map_exception_to_error_data
                 error_data = map_exception_to_error_data(e)

                 yield f"event: processing_error\ndata: {json.dumps(error_data)}\n\n"
                 return

            if not retrieval_result.chunks:
                yield f"data: {json.dumps('No relevant documents found.')}\n\n"
                yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"
                return

            # Emit Routing Info
            yield f"event: routing\ndata: {json.dumps({'categories': ['Imported Docs'], 'confidence': 1.0})}\n\n"

            # Emit Quality Score
            if retrieval_result.chunks:
                scores = []
                for c in retrieval_result.chunks:
                    if isinstance(c, dict):
                        scores.append(float(c.get("score", 0)))
                    else:
                        scores.append(float(getattr(c, "score", 0)))
                
                max_score = max(scores) if scores else 0
                quality_data = {
                    "total": round(max_score * 100, 1),
                    "retrieval": round(max_score * 100, 1),
                    "generation": 0
                }
                yield f"event: quality\ndata: {json.dumps(quality_data)}\n\n"


            # Emit conversation_id IMMEDIATELY for threading (to match Agent behavior)
            import uuid
            final_conversation_id = request.conversation_id or str(uuid.uuid4())
            logger.info(f"EMITTING conversation_id SSE event upfront: {final_conversation_id}")
            yield f"event: conversation_id\ndata: {json.dumps(final_conversation_id)}\n\n"

            # Stream the answer
            full_answer = ""
            collected_sources = []
            stream_model = ""
            stream_start_time = time.perf_counter()  # Track generation latency
            
            # Extract User ID (Phase 3 Memory)
            user_id = http_request.headers.get("X-User-ID", "default_user")

            async for event_dict in generation_service.generate_stream(
                query=request.query,
                candidates=retrieval_result.chunks,
                conversation_history=None,
                options={
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "model": request.options.model if request.options else None
                },
            ):
                event = event_dict.get("event", "message")
                data = event_dict.get("data", "")
                
                # Accumulate answer for history
                if event == "token":
                    full_answer += str(data)
                elif event == "sources":
                    collected_sources = data
                elif event == "done" and isinstance(data, dict):
                    stream_model = data.get("model", "")

                # ALWAYS JSON encode data to preserve newlines and special chars
                data_str = json.dumps(data)

                yield f"event: {event}\ndata: {data_str}\n\n"
            
            # Normalize citation variants for storage/metrics.
            full_answer = generation_service._normalize_citations(full_answer)
            stream_latency_ms = (time.perf_counter() - stream_start_time) * 1000

            # SAVE INTERACTION TO HISTORY
            try:
                # Truncate for summary
                summary_text = full_answer[:200] + "..." if len(full_answer) > 200 else full_answer
                title_text = request.query[:50] + "..." if len(request.query) > 50 else request.query
                
                from datetime import datetime
                from src.core.generation.domain.memory_models import ConversationSummary
                from src.api.deps import _get_async_session_maker
                
                async with _get_async_session_maker()() as session:
                    # Try to find existing conversation (for threading)
                    existing_summary = None
                    if request.conversation_id:
                        existing_summary = await session.get(ConversationSummary, final_conversation_id)

                    # Prepare stats for persistence
                    persistence_quality = None
                    if retrieval_result and retrieval_result.chunks:
                        p_scores = []
                        for c in retrieval_result.chunks:
                            if isinstance(c, dict):
                                p_scores.append(float(c.get("score", 0)))
                            else:
                                p_scores.append(float(getattr(c, "score", 0)))
                        p_max = max(p_scores) if p_scores else 0
                        persistence_quality = {
                            "total": round(p_max * 100, 1),
                            "retrieval": round(p_max * 100, 1),
                            "generation": 0
                        }
                    
                    persistence_routing = {"categories": ["Imported Docs"], "confidence": 1.0}

                    if existing_summary:
                        # UPDATE existing conversation
                        # 1. Append to history
                        history = existing_summary.metadata_.get("history", [])
                        history.append({
                            "query": request.query, 
                            "answer": full_answer,
                            "sources": collected_sources,
                            "quality_score": persistence_quality,
                            "routing_info": persistence_routing,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        existing_summary.metadata_["history"] = history
                        
                        # 2. Update top-level metadata
                        existing_summary.metadata_["query"] = request.query
                        existing_summary.metadata_["answer"] = full_answer
                        existing_summary.metadata_["timestamp"] = datetime.utcnow().isoformat()
                        
                        # 3. Flag as modified for SQLAlchemy
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(existing_summary, "metadata_")
                        
                        session.add(existing_summary)
                        await session.commit()
                        logger.info(f"Updated RAG conversation history: {existing_summary.id}")
                    else:
                        # INSERT new conversation
                        # Use the final_conversation_id we generated at the start
                        new_summary = ConversationSummary(
                            id=final_conversation_id,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            title=title_text,
                            summary=summary_text,
                            metadata_={
                                "query": request.query,
                                "answer": full_answer,
                                "sources": collected_sources,
                                "model": "rag-default",
                                "mode": "rag",
                                "history": [{
                                    "query": request.query, 
                                    "answer": full_answer,
                                    "sources": collected_sources,
                                    "quality_score": persistence_quality,
                                    "routing_info": persistence_routing,
                                    "timestamp": datetime.utcnow().isoformat()
                                }]
                            }
                        )
                        session.add(new_summary)
                        await session.commit()
                        logger.info(f"Saved RAG conversation history: {new_summary.id}")
                    
            except Exception as e:
                logger.error(f"Failed to save RAG conversation history: {e}")

            # LOG TO CONTEXT GRAPH (Async - Fire and forget)
            try:
                from src.core.graph.application.context_writer import context_graph_writer
                
                # Transform collected sources to graph format
                # collected_sources is list of dicts from 'sources' event
                graph_sources = [
                    {"chunk_id": s.get("chunk_id"), "document_id": s.get("document_id"), "score": s.get("score")}
                    for s in collected_sources
                ] if collected_sources else []
                
                # Call log_turn asynchronously
                asyncio.create_task(
                    context_graph_writer.log_turn(
                        conversation_id=final_conversation_id,
                        tenant_id=tenant_id,
                        query=request.query,
                        answer=full_answer,
                        sources=graph_sources,
                        model=stream_model,
                        latency_ms=stream_latency_ms
                    )
                )
                logger.debug(f"Scheduled context graph logging for stream query {final_conversation_id}")
            except Exception as e:
                logger.warning(f"Failed to schedule context graph logging for stream: {e}")

            # RECORD METRICS for streaming queries
            try:
                from src.api.config import settings
                from src.core.admin_ops.application.metrics.collector import MetricsCollector, QueryMetrics
                from src.shared.identifiers import generate_query_id
                from src.core.utils.tokenizer import Tokenizer
                
                # Pricing map (USD per 1k tokens) - Keep aligned with providers
                MODEL_PRICING = {
                    "gpt-4o": {"input": 0.005, "output": 0.015},
                    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
                    "o1": {"input": 0.015, "output": 0.06},
                    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
                    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
                    "default": {"input": 0.00015, "output": 0.0006}  # Fallback to mini rates
                }
                
                query_id = generate_query_id()
                
                # 1. Count Output Tokens
                output_tokens = Tokenizer.count_tokens(full_answer, stream_model)
                
                # 2. Count Input Tokens (Query + Chunks)
                # Reconstruct rough context string to estimate input tokens
                chunk_text = "\n".join([getattr(c, "content", "") for c in retrieval_result.chunks]) if retrieval_result.chunks else ""
                input_text = f"{request.query}\n{chunk_text}"
                input_tokens = Tokenizer.count_tokens(input_text, stream_model)
                
                # 3. Calculate Cost
                # Match model to pricing
                pricing = MODEL_PRICING.get("default")
                for key, rates in MODEL_PRICING.items():
                    if key in stream_model.lower():
                        pricing = rates
                        break
                        
                cost_estimate = (
                    (input_tokens * pricing["input"] / 1000) + 
                    (output_tokens * pricing["output"] / 1000)
                )
                
                # Infer provider from model name
                provider = "openai" if "gpt" in stream_model.lower() else "anthropic" if "claude" in stream_model.lower() else "unknown"
                
                metrics_obj = QueryMetrics(
                    query_id=query_id,
                    tenant_id=tenant_id,
                    query=request.query,
                    operation="rag_query",
                    response=full_answer[:500] if len(full_answer) > 500 else full_answer,
                    chunks_retrieved=len(retrieval_result.chunks),
                    chunks_used=len(retrieval_result.chunks),
                    cache_hit=retrieval_result.cache_hit,
                    tokens_used=input_tokens + output_tokens,
                    output_tokens=output_tokens,
                    generation_latency_ms=stream_latency_ms,
                    total_latency_ms=stream_latency_ms,
                    cost_estimate=cost_estimate,
                    model=stream_model,
                    provider=provider,
                    success=True,
                    conversation_id=final_conversation_id,
                    sources_cited=len(collected_sources),
                    answer_length=len(full_answer),
                )
                
                collector = MetricsCollector(redis_url=settings.db.redis_url)
                await collector.record(metrics_obj)
                await collector.close()
                logger.debug(f"Recorded streaming metrics for query {query_id}")
            except Exception as e:
                logger.warning(f"Failed to record streaming metrics: {e}")

            yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"

        except Exception as e:
            # Generic Provider Error Handling
            # We assume core provider exceptions are available or recognizable by name
            
            error_code = "error"
            provider = "System"
            message = str(e)
            is_handled_error = False
            
            # Helper to safely get provider from exception or text
            def get_provider(exc):
                if hasattr(exc, "provider") and exc.provider:
                    return exc.provider.title()
                return "Provider"

            # 1. Try to match specific known provider errors classes
            try:
                from src.core.generation.domain.provider_models import (
                    RateLimitError, 
                    AuthenticationError, 
                    InvalidRequestError,
                    ProviderUnavailableError
                )
                
                if isinstance(e, RateLimitError):
                    error_code = "rate_limit"
                    provider = get_provider(e)
                    message = "Rate limit exceeded"
                    is_handled_error = True
                
                elif isinstance(e, AuthenticationError):
                    error_code = "auth_error"
                    provider = get_provider(e)
                    message = "Authentication failed"
                    is_handled_error = True

                elif isinstance(e, InvalidRequestError):
                    # Could be context length or other invalid params
                    error_code = "context_length" if "context" in str(e).lower() else "invalid_request"
                    provider = get_provider(e)
                    message = "Invalid request"
                    is_handled_error = True

                elif isinstance(e, ProviderUnavailableError):
                    error_code = "provider_error"
                    provider = get_provider(e)
                    message = "Service unavailable"
                    is_handled_error = True
                    
            except ImportError:
                # Fallback to string matching if imports fail/circular dep
                name = type(e).__name__
                if "RateLimitError" in name:
                    error_code = "rate_limit"
                    is_handled_error = True
                elif "AuthenticationError" in name:
                    error_code = "auth_error"
                    is_handled_error = True
                elif "InvalidRequestError" in name:
                    error_code = "context_length" if "context" in str(e).lower() else "invalid_request"
                    is_handled_error = True
                elif "ProviderUnavailableError" in name:
                    error_code = "provider_error"
                    is_handled_error = True
                
                if is_handled_error and hasattr(e, "provider"):
                     provider = e.provider.title()
            
            if is_handled_error:
                 logger.warning(f"Handled Provider Error: {error_code} from {provider} - {e}")
                 error_data = {
                     "code": error_code, 
                     "message": message,
                     "provider": provider
                 }
                 yield f"event: processing_error\ndata: {json.dumps(error_data)}\n\n"
                 return

            logger.exception(f"Stream generation failed: {e}")
            yield f"event: processing_error\ndata: {json.dumps(str(e))}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Encoding": "none",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/stream",
    summary="Stream Query Response",
    description="Stream the query response using Server-Sent Events.",
    operation_id="query_stream_get",
)
async def query_stream_get(
    http_request: Request,
    query: str,
    agent_mode: bool = False,
    model: str = None,  # Added model param
    conversation_id: str = None,
    session: AsyncSession = Depends(get_db_session),
):
    return await _query_stream_impl(
        http_request=http_request,
        request=None,
        query=query,
        agent_mode=agent_mode,
        model=model,        # Pass model param
        conversation_id=conversation_id,
        session=session,
    )


@router.post(
    "/stream",
    summary="Stream Query Response",
    description="Stream the query response using Server-Sent Events.",
    operation_id="query_stream_post",
)
async def query_stream_post(
    http_request: Request,
    request: QueryRequest,
    session: AsyncSession = Depends(get_db_session),
):
    return await _query_stream_impl(
        http_request=http_request,
        request=request,
        session=session,
    )
