"""
Judge Service
=============

Implements LLM-as-a-Judge for automated evaluation of RAG outputs.

.. deprecated::
    This service is deprecated and maintained only as a fallback. 
    For new code, use :class:`src.core.evaluation.ragas_service.RagasService`
    which wraps the official Ragas library and falls back to this service
    when Ragas is not installed.
"""


import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from src.core.providers.base import BaseLLMProvider
from src.core.generation.registry import PromptRegistry
from src.core.observability.tracer import trace_span

logger = logging.getLogger(__name__)

@dataclass
class EvaluationResult:
    score: float  # 0.0 to 1.0
    reasoning: str
    metadata: Dict[str, Any]

class JudgeService:
    """
    Evaluates RAG outputs for faithfulness and relevance.
    """

    def __init__(self, llm: BaseLLMProvider, prompt_registry: PromptRegistry):
        self.llm = llm
        self.prompts = prompt_registry

    @trace_span("JudgeService.evaluate_faithfulness")
    async def evaluate_faithfulness(self, query: str, context: str, answer: str) -> EvaluationResult:
        """
        Check if the answer is supported by the context.
        """
        prompt_tmpl = self.prompts.get_prompt("faithfulness_judge")
        prompt = prompt_tmpl.format(query=query, context=context, answer=answer)
        
        # We use a lower temperature for evaluation
        res = await self.llm.generate(prompt=prompt, temperature=0.0)
        return self._parse_evaluation(res.text)

    @trace_span("JudgeService.evaluate_relevance")
    async def evaluate_relevance(self, query: str, answer: str) -> EvaluationResult:
        """
        Check if the answer directly addresses the query.
        """
        prompt_tmpl = self.prompts.get_prompt("relevance_judge")
        prompt = prompt_tmpl.format(query=query, answer=answer)
        
        res = await self.llm.generate(prompt=prompt, temperature=0.0)
        return self._parse_evaluation(res.text)

    def _parse_evaluation(self, text: str) -> EvaluationResult:
        """
        Simple parser for judge output. 
        Expected format:
        Score: [0-1]
        Reasoning: [Explanation]
        """
        lines = text.strip().split("\n")
        score = 0.0
        reasoning = ""
        
        for line in lines:
            if line.lower().startswith("score:"):
                try:
                    score = float(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.lower().startswith("reasoning:"):
                reasoning = line.split(":")[1].strip()
        
        # If reasoning spans multiple lines
        if not reasoning and len(lines) > 1:
            reasoning = text
            
        return EvaluationResult(
            score=min(max(score, 0.0), 1.0),
            reasoning=reasoning,
            metadata={"raw_output": text}
        )
