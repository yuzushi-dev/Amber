"""
Query API Routes
================

Endpoints for querying the knowledge base.
Phase 2: Baseline RAG implementation with vector retrieval and LLM generation.
"""

import json
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
            options=QueryOptions(agent_mode=agent_mode),
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

                    # Initialize Tools
                    retrieval_tool_def = create_retrieval_tool(retrieval_service, tenant_id)
                    tool_map = {
                        retrieval_tool_def["name"]: retrieval_tool_def["func"]
                    }
                    tool_schemas = [retrieval_tool_def["schema"]]

                    # Add Graph Tool
                    tool_map["query_graph"] = query_graph
                    tool_schemas.extend(GRAPH_TOOLS)
                    
                    # Add Filesystem Tools (Maintainer only)
                    if request.options.agent_role == "maintainer":
                        fs_tools = create_filesystem_tools(base_path=".") 
                        for t in fs_tools:
                            tool_map[t["name"]] = t["func"]
                            tool_schemas.append(t["schema"])
                    
                    
                    # Add Connector Tools - DYNAMICALLY LOAD
                    logger.info("Starting Agent Mode Setup...")
                    # Fetch active credentials for ALL active connectors
                    from src.api.routes.connectors import CONNECTOR_REGISTRY
                    from src.core.ingestion.domain.connector_state import ConnectorState
                    from src.api.deps import _get_async_session_maker
                    from sqlalchemy import select

                    c_tools_count = 0
                    async with _get_async_session_maker()() as session:
                        logger.info("DB Session created for Agent Setup")
                        # Select all active connectors for this tenant
                        result = await session.execute(
                            select(ConnectorState).where(
                                ConnectorState.tenant_id == tenant_id
                            )
                        )
                        c_states = result.scalars().all()
                        
                        for c_state in c_states:
                            if not c_state.sync_cursor:
                                continue
                                
                            c_type = c_state.connector_type
                            if c_type in CONNECTOR_REGISTRY:
                                try:
                                    logger.info(f"Initializing connector: {c_type}")
                                    ConnectorClass = CONNECTOR_REGISTRY[c_type]
                                    creds = c_state.sync_cursor
                                    
                                    # Initialize with specific params based on type if needed, 
                                    # but BaseConnector usually takes kwargs or we rely on authenticated() 
                                    # to set state. 
                                    # Actually, Zendesk needs subdomain in init, Carbonio needs host.
                                    # We can try to pass relevant args from creds to init.
                                    
                                    init_kwargs = {}
                                    if c_type == "zendesk":
                                        init_kwargs["subdomain"] = creds.get("subdomain", "")
                                    elif c_type == "confluence":
                                        init_kwargs["base_url"] = creds.get("base_url", "")
                                    elif c_type == "carbonio":
                                        init_kwargs["host"] = creds.get("host", "")
                                    
                                    connector_instance = ConnectorClass(**init_kwargs)
                                    
                                    # Authenticate
                                    auth_success = await connector_instance.authenticate(creds)
                                    if auth_success:
                                        c_tools = connector_instance.get_agent_tools()
                                        for t in c_tools:
                                            tool_map[t["name"]] = t["func"]
                                            tool_schemas.append(t["schema"])
                                            c_tools_count += 1
                                        logger.info(f"Loaded {len(c_tools)} tools from {c_type}")
                                    else:
                                        logger.warning(f"Failed to authenticate {c_type} during agent setup")
                                except Exception as e:
                                    logger.error(f"Error loading connector {c_type}: {e}")

                    
                    logger.info(f"Agent tools loaded. Total extra tools: {c_tools_count}")
                    
                    # Initialize Agent
                    agent = AgentOrchestrator(
                        generation_service=generation_service,
                        tools=tool_map,
                        tool_schemas=tool_schemas,
                        system_prompt=AGENT_SYSTEM_PROMPT
                    )

                    logger.info("AgentOrchestrator initialized. Starting Run...")

                    # Load previous conversation history if continuing a thread
                    conversation_history = []
                    if request.conversation_id:
                        try:
                            from src.core.generation.domain.memory_models import ConversationSummary  # Import here for history loading
                            async with _get_async_session_maker()() as history_session:
                                existing_conv = await history_session.get(ConversationSummary, request.conversation_id)
                                if existing_conv and existing_conv.metadata_:
                                    saved_history = existing_conv.metadata_.get("history", [])
                                    for entry in saved_history:
                                        # Convert saved history to message format
                                        conversation_history.append({
                                            "role": "user",
                                            "content": entry.get("query", "")
                                        })
                                        conversation_history.append({
                                            "role": "assistant", 
                                            "content": entry.get("answer", "")
                                        })
                                    logger.info(f"Loaded {len(saved_history)} previous exchanges for threading")
                        except Exception as e:
                            logger.warning(f"Failed to load conversation history: {e}")

                    # Run Agent with context
                    agent_response = await agent.run(
                        query=request.query,
                        conversation_id=agent_conversation_id, # Use pre-calculated ID
                        conversation_history=conversation_history if conversation_history else None
                    )
                    
                    logger.info("Agent Run Complete.")

                    # SAVE AGENT INTERACTION TO HISTORY
                    # We do this BEFORE yielding to client to ensure persistence even if client disconnects
                    try:
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
                                        # Extract tool names safely (handle OpenAI format {"function": {"name": ...}})
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
                            
                    except Exception as e:
                        logger.error(f"Failed to save AGENT conversation history: {e}")

                    # Stream the result as if it were tokens
                    # (AgentOrchestrator returns full answer currently)
                    yield f"event: message\ndata: {json.dumps(agent_response.answer)}\n\n"

                    yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"
                    return

                except Exception as e:
                    logger.error(f"Agent stream failed: {e}")
                    yield f"event: error\ndata: {json.dumps(f'Agent error: {str(e)}')}\n\n"
                    return

            # STANDARD RAG PIPELINE
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
                    "tenant_id": tenant_id
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
    conversation_id: str = None,
    session: AsyncSession = Depends(get_db_session),
):
    return await _query_stream_impl(
        http_request=http_request,
        request=None,
        query=query,
        agent_mode=agent_mode,
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
