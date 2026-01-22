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
                ollama_base_url=settings.ollama_base_url,
                default_embedding_provider=settings.default_embedding_provider,
                default_embedding_model=settings.default_embedding_model,
                redis_url=settings.db.redis_url,
                config=retrieval_config,
            )

            _generation_service = GenerationService(
                openai_api_key=openai_key or None,
                anthropic_api_key=anthropic_key or None,
                ollama_base_url=settings.ollama_base_url,
                default_llm_provider=settings.default_llm_provider,
                default_llm_model=settings.default_llm_model,
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
                # Extract User ID (Phase 3 Memory)
                user_id = http_request.headers.get("X-User-ID", "default_user")

                # Generate answer from chunks
                gen_result = await generation_service.generate(
                    query=request.query,
                    candidates=retrieval_result.chunks,
                    include_trace=include_trace,
                    options={
                        "user_id": user_id,
                        "tenant_id": tenant_id
                    }
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

        # Log to Context Graph (background task - fire and forget)
        try:
            import asyncio
            from src.core.graph.context_writer import context_graph_writer
            from src.core.security.pii_scrubber import PIIScrubber

            
            source_data = [
                {"chunk_id": s.chunk_id, "document_id": s.document_id, "score": s.score}
                for s in sources
            ] if sources else []
            
            # S02: Scrub PII from logs
            scrubber = PIIScrubber()
            safe_query = scrubber.scrub_text(request.query)
            safe_answer = scrubber.scrub_text(answer)

            asyncio.create_task(
                context_graph_writer.log_turn(
                    conversation_id=request.conversation_id or query_id,
                    tenant_id=tenant_id,
                    query=safe_query,
                    answer=safe_answer,
                    sources=source_data,
                    trace_steps=trace_steps if include_trace else None,
                    model=query_metrics.model if 'query_metrics' in dir() else None,
                    latency_ms=total_ms,
                )
            )
        except Exception as e:
            logger.warning(f"Failed to schedule context graph logging: {e}")

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


async def _query_stream_impl(
    http_request: Request,
    request: QueryRequest = None,
    query: str = None,
    agent_mode: bool = False,
    conversation_id: str = None,  # Added for threading support
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

        # =========================================================================
        # STICKY MODE CHECK
        # =========================================================================
        # Check if this is a continuation of an AGENT conversation
        if request.conversation_id and not (request.options and request.options.agent_mode):
            try:
                from src.core.models.memory import ConversationSummary
                from src.api.deps import _async_session_maker
                
                async with _async_session_maker() as session:
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

                    from src.core.agent.orchestrator import AgentOrchestrator
                    from src.core.agent.prompts import AGENT_SYSTEM_PROMPT
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
                    from src.core.models.connector_state import ConnectorState
                    from src.api.deps import _async_session_maker
                    from sqlalchemy import select

                    c_tools_count = 0
                    async with _async_session_maker() as session:
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
                            from src.core.models.memory import ConversationSummary  # Import here for history loading
                            async with _async_session_maker() as history_session:
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
                        from src.core.models.memory import ConversationSummary
                        from src.api.deps import _async_session_maker
                        
                        async with _async_session_maker() as session:
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
                }
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
                from src.core.models.memory import ConversationSummary
                from src.api.deps import _async_session_maker
                
                async with _async_session_maker() as session:
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
                from src.core.graph.context_writer import context_graph_writer
                
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
                from src.core.metrics.collector import MetricsCollector, QueryMetrics
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
):
    return await _query_stream_impl(
        http_request=http_request,
        request=None,
        query=query,
        agent_mode=agent_mode,
        conversation_id=conversation_id,
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
):
    return await _query_stream_impl(
        http_request=http_request,
        request=request,
    )
