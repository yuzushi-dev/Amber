"""
Agent Orchestrator
==================

A generic ReAct (Reasoning + Acting) agent that executes a loop:
1. Think (Call LLM)
2. Act (Execute Tool)
3. Observe (Add Tool Output to History)
4. Repeat until Answer
"""

import logging
import json
from typing import Any, Callable

from src.core.generation.application.generation_service import GenerationService
from src.shared.kernel.models.query import QueryResponse, TimingInfo
from src.shared.kernel.observability import trace_span

logger = logging.getLogger(__name__)

class AgentOrchestrator:
    """
    Manages the ReAct loop for an agent.
    """

    def __init__(
        self,
        generation_service: GenerationService,
        tools: dict[str, Callable],
        tool_schemas: list[dict[str, Any]],
        system_prompt: str,
        max_steps: int = 10
    ):
        self.gen = generation_service
        self.tools = tools
        self.tool_schemas = tool_schemas
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    @trace_span("AgentOrchestrator.run")
    async def run(
        self, 
        query: str, 
        conversation_id: str | None = None,
        conversation_history: list[dict] | None = None
    ) -> QueryResponse:
        """
        Execute the agent loop for a given query.
        
        Args:
            query: The user's current query
            conversation_id: Optional ID for threading
            conversation_history: Optional list of previous messages [{"role": "user/assistant", "content": "..."}]
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
        ]
        
        # Insert previous conversation history for context
        if conversation_history:
            for msg in conversation_history:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        
        # Add current user query
        messages.append({"role": "user", "content": query})
        
        trace = []
        steps_taken = 0
        
        while steps_taken < self.max_steps:
             # 1. Think
            tool_defs = self._get_tool_definitions() if self.tools else None
            response = await self.gen.chat_completion(
                messages=messages,
                tools=tool_defs
            )
            
            # OpenAI ChatCompletion object
            message = response.choices[0].message
            messages.append(message)
            
            # 2. Check for Tool Calls
            if not message.tool_calls:
                # Agent is done, returned a final answer
                result = QueryResponse(
                    answer=message.content,
                    sources=[], # TODO: Extract sources from tool outputs
                    timing=TimingInfo(total_ms=0, retrieval_ms=0, generation_ms=0), # TODO: Track timing
                    conversation_id=conversation_id,
                    trace=trace 
                )
                logger.info(f"Agent finished with answer. Result: {result.answer[:50]}...")
                return result
            
            # 3. Act (Execute Tools)
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                args_str = tool_call.function.arguments
                call_id = tool_call.id
                
                try:
                    args = json.loads(args_str)
                    if func_name in self.tools:
                        logger.info(f"Agent calling tool: {func_name} args={args}")
                        result = await self.tools[func_name](**args)
                        output = str(result)
                    else:
                        output = f"Error: Tool '{func_name}' not found."
                except Exception as e:
                    output = f"Error executing '{func_name}': {str(e)}"
                
                # 4. Observe
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": output
                })
                
                trace.append({
                    "step": f"tool_call:{func_name}",
                    "details": {
                        "args": args_str,
                        "output": output[:500] + "..." # Truncate for trace
                    }
                })
            
            steps_taken += 1
            
        result = QueryResponse(
            answer="I reached the maximum number of steps without finding a definitive answer.",
            conversation_id=conversation_id,
            trace=trace,
            timing=TimingInfo(total_ms=0, retrieval_ms=0, generation_ms=0)
        )
        logger.info(f"Agent finished max steps. Result: {result.answer[:50]}...")
        return result

    def _get_tool_definitions(self) -> list[dict]:
        """Return the tool schemas for the LLM."""
        return self.tool_schemas
