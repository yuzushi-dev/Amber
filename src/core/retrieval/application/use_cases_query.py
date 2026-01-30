"""
Query Use Cases
===============

Application layer use cases for querying the knowledge base.
Handles orchestration of:
- Structured Queries
- Agent Logic
- RAG Pipeline
"""

import logging
import time
from typing import Optional, Any

from src.shared.kernel.models.query import (
    QueryRequest,
    QueryResponse,
    StructuredQueryResponse,
    TimingInfo,
    TraceStep,
    Source,
)

from src.core.retrieval.application.retrieval_service import RetrievalService
from src.core.generation.application.generation_service import GenerationService
from src.core.admin_ops.application.metrics.collector import MetricsCollector

logger = logging.getLogger(__name__)


class QueryUseCase:
    """
    Use case for executing queries (Structured, Agentic, or RAG).
    """

    def __init__(
        self,
        retrieval_service: RetrievalService,
        generation_service: GenerationService,
        metrics_collector: MetricsCollector,
    ):
        self.retrieval_service = retrieval_service
        self.generation_service = generation_service
        self.metrics = metrics_collector

    async def execute(
        self,
        request: QueryRequest,
        tenant_id: str,
        http_request_state: Any = None, # For permissions/context if needed, or extract needed data
        user_id: str = "default_user",
    ) -> QueryResponse | StructuredQueryResponse:
        """
        Execute the query pipeline.
        
        Args:
            request: The query request.
            tenant_id: The tenant context.
            http_request_state: Optional state from FastAPI request (for permissions).
            user_id: User identifier.
            
        Returns:
            QueryResponse or StructuredQueryResponse.
        """
        start_time = time.perf_counter()
        
        # Options
        include_trace = request.options.include_trace if request.options else False
        max_chunks = request.options.max_chunks if request.options else 10
        trace_steps: list[TraceStep] = []

        # 1. STRUCTURED QUERY CHECK
        try:
            from src.core.retrieval.application.query.structured_query import structured_executor

            structured_result = await structured_executor.try_execute(
                query=request.query,
                tenant_id=tenant_id,
            )

            if structured_result and structured_result.success:
                logger.info(
                    f"Structured query executed: {structured_result.query_type.value} "
                    f"in {structured_result.execution_time_ms:.1f}ms"
                )
                
                count = structured_result.count
                query_type = structured_result.query_type.value
                message = self._format_structured_message(query_type, count)

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
            logger.debug(f"Structured query check failed, using RAG: {e}")

        # 2. AGENTIC MODE
        if request.options and request.options.agent_mode:
            try:
                return await self._execute_agent(request, tenant_id, start_time)
            except Exception as e:
                logger.error(f"Agent execution failed: {e}")
                # Fallback to standard RAG
        
        # 3. RAG PIPELINE
        # Generate query ID
        from src.shared.identifiers import generate_query_id
        query_id = generate_query_id()

        try:
             async with self.metrics.track_query(query_id, tenant_id, request.query) as query_metrics:
                query_metrics.conversation_id = request.conversation_id or query_id

                # Step 1: Parse
                step_start = time.perf_counter()
                trace_steps.append(TraceStep(
                    step="parse_query",
                    duration_ms=(time.perf_counter() - step_start) * 1000,
                    details={"query_length": len(request.query), "query_id": query_id},
                ))

                # Step 2: Retrieval
                step_start = time.perf_counter()
                document_ids = request.filters.document_ids if request.filters else None

                retrieval_result = await self.retrieval_service.retrieve(
                    query=request.query,
                    tenant_id=tenant_id,
                    document_ids=document_ids,
                    top_k=max_chunks,
                    include_trace=include_trace,
                    options=request.options,
                    history=None, 
                )

                retrieval_ms = (time.perf_counter() - step_start) * 1000
                query_metrics.retrieval_latency_ms = retrieval_ms
                query_metrics.chunks_retrieved = len(retrieval_result.chunks)
                query_metrics.cache_hit = retrieval_result.cache_hit

                for rt in retrieval_result.trace:
                    trace_steps.append(TraceStep(
                        step=rt["step"],
                        duration_ms=rt.get("duration_ms", 0),
                        details={k: v for k, v in rt.items() if k not in ("step", "duration_ms")},
                    ))

                # Step 3: Generation
                step_start = time.perf_counter()
                
                if not retrieval_result.chunks:
                    answer = self._get_empty_result_message(request.query)
                    sources: list[Source] = []
                    follow_ups = ["What documents are available?", "How do I upload documents?"]
                else:
                    gen_result = await self.generation_service.generate(
                        query=request.query,
                        candidates=retrieval_result.chunks,
                        include_trace=include_trace,
                        options={
                            "user_id": user_id,
                            "tenant_id": tenant_id,
                            "model": request.options.model if request.options else None
                        }
                    )

                    answer = gen_result.answer
                    self._update_metrics_from_generation(query_metrics, gen_result, answer)
                    
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

                    for gt in gen_result.trace:
                        trace_steps.append(TraceStep(
                            step=gt["step"],
                            duration_ms=gt.get("duration_ms", 0),
                            details={k: v for k, v in gt.items() if k not in ("step", "duration_ms")},
                        ))

                generation_ms = (time.perf_counter() - step_start) * 1000
                query_metrics.generation_latency_ms = generation_ms

        except Exception as e:
            logger.exception(f"Query failed: {e}")
            return self._fallback_response(request, start_time, str(e))

        total_ms = (time.perf_counter() - start_time) * 1000

        # Background Logging (Context Graph)
        self._schedule_context_logging(
            query_id=query_id,
            conversation_id=request.conversation_id or query_id,
            tenant_id=tenant_id,
            query=request.query,
            answer=answer,
            sources=sources,
            trace_steps=trace_steps if include_trace else None,
            total_ms=total_ms,
            model=query_metrics.model if 'query_metrics' in locals() else None
        )

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

    async def _execute_agent(self, request: QueryRequest, tenant_id: str, start_time: float):
        from src.core.generation.application.agent.orchestrator import AgentOrchestrator
        from src.core.generation.application.agent.prompts import AGENT_SYSTEM_PROMPT
        from src.core.tools.retrieval import create_retrieval_tool
        from src.core.tools.filesystem import create_filesystem_tools
        
        # Tools Setup
        retrieval_tool_def = create_retrieval_tool(self.retrieval_service, tenant_id)
        tool_map = {retrieval_tool_def["name"]: retrieval_tool_def["func"]}
        tool_schemas = [retrieval_tool_def["schema"]]

        agent_role = request.options.agent_role
        if agent_role == "maintainer":
             fs_tools = create_filesystem_tools(base_path=".") 
             for t in fs_tools:
                 tool_map[t["name"]] = t["func"]
                 tool_schemas.append(t["schema"])
        else:
             from src.core.tools.graph import GRAPH_TOOLS, query_graph
             tool_map["query_graph"] = query_graph
             tool_schemas.extend(GRAPH_TOOLS)
        
        agent = AgentOrchestrator(
            generation_service=self.generation_service,
            tools=tool_map,
            tool_schemas=tool_schemas,
            system_prompt=AGENT_SYSTEM_PROMPT
        )
        
        agent_response = await agent.run(
            query=request.query,
            conversation_id=request.conversation_id
        )
        
        total_ms = (time.perf_counter() - start_time) * 1000
        agent_response.timing.total_ms = round(total_ms, 2)
        return agent_response

    def _format_structured_message(self, query_type: str, count: int) -> str:
        if "count" in query_type:
            return f"Found {count} {query_type.replace('count_', '').replace('_', ' ')}"
        return f"Retrieved {count} {query_type.replace('list_', '').replace('_', ' ')}"

    def _get_empty_result_message(self, query_text: str) -> str:
        return (
            "I couldn't find any relevant information in the knowledge base "
            f"to answer: \"{query_text[:100]}...\"\n\n"
            "This could mean:\n"
            "- No documents have been uploaded yet\n"
            "- The query doesn't match available content\n"
            "- Try rephrasing your question"
        )

    def _update_metrics_from_generation(self, metrics, result, answer):
        metrics.tokens_used = result.tokens_used
        metrics.input_tokens = result.input_tokens
        metrics.output_tokens = result.output_tokens
        metrics.cost_estimate = result.cost_estimate
        metrics.model = result.model
        metrics.provider = result.provider
        metrics.sources_cited = len(result.sources)
        metrics.answer_length = len(answer)
        metrics.operation = "rag_query"
        metrics.response = answer[:500] if len(answer) > 500 else answer

    def _schedule_context_logging(self, query_id, conversation_id, tenant_id, query, answer, sources, trace_steps, total_ms, model):
        try:
            import asyncio
            from src.core.graph.application.context_writer import context_graph_writer
            from src.core.security.pii_scrubber import PIIScrubber
            
            source_data = [
                {"chunk_id": s.chunk_id, "document_id": s.document_id, "score": s.score}
                for s in sources
            ] if sources else []
            
            scrubber = PIIScrubber()
            safe_query = scrubber.scrub_text(query)
            safe_answer = scrubber.scrub_text(answer)

            asyncio.create_task(
                context_graph_writer.log_turn(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    query=safe_query,
                    answer=safe_answer,
                    sources=source_data,
                    trace_steps=trace_steps,
                    model=model,
                    latency_ms=total_ms,
                )
            )
        except Exception as e:
            logger.warning(f"Failed to schedule context graph logging: {e}")

    def _fallback_response(self, request, start_time, error) -> QueryResponse:
        elapsed = (time.perf_counter() - start_time) * 1000
        return QueryResponse(
            answer=f"I'm unable to process your query at the moment. Error: {error}",
            sources=[],
            trace=None,
            timing=TimingInfo(total_ms=round(elapsed, 2), retrieval_ms=None, generation_ms=None),
            conversation_id=request.conversation_id,
            follow_up_questions=["Check configuration"],
        )
