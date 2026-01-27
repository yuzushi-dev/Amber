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
from dataclasses import dataclass
from typing import Any

from src.core.generation.application.registry import PromptRegistry
from src.shared.kernel.observability import trace_span
from src.core.generation.domain.ports.providers import LLMProviderPort

logger = logging.getLogger(__name__)

@dataclass
class EvaluationResult:
    score: float  # 0.0 to 1.0
    reasoning: str
    metadata: dict[str, Any]

class JudgeService:
    """
    Evaluates RAG outputs for faithfulness and relevance.
    """

    def __init__(self, llm: LLMProviderPort, prompt_registry: PromptRegistry):
        self.llm = llm
        self.prompts = prompt_registry

    @trace_span("JudgeService.evaluate_faithfulness")
    async def evaluate_faithfulness(
        self,
        query: str,
        context: str,
        answer: str,
        tenant_config: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """
        Check if the answer is supported by the context.
        """
        prompt_tmpl = self.prompts.get_prompt("faithfulness_judge")
        prompt = prompt_tmpl.format(query=query, context=context, answer=answer)

        # We use a lower temperature for evaluation
        from src.shared.kernel.runtime import get_settings
        from src.core.generation.application.llm_steps import resolve_llm_step_config
        from src.core.generation.domain.ports.provider_factory import get_provider_factory
        from src.core.generation.domain.provider_models import ProviderTier

        settings = get_settings()
        tenant_config = tenant_config or {}
        llm_cfg = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="admin.judge_faithfulness",
            settings=settings,
        )

        provider = self.llm
        try:
            provider = get_provider_factory().get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
        except Exception as e:
            logger.debug(f"Failed to resolve provider override for judge: {e}")

        kwargs: dict[str, Any] = {}
        if llm_cfg.temperature is not None:
            kwargs["temperature"] = llm_cfg.temperature
        if llm_cfg.seed is not None:
            kwargs["seed"] = llm_cfg.seed
        if llm_cfg.model is not None:
            kwargs["model"] = llm_cfg.model

        res = await provider.generate(prompt=prompt, **kwargs)
        return self._parse_evaluation(res.text)

    @trace_span("JudgeService.evaluate_relevance")
    async def evaluate_relevance(
        self,
        query: str,
        answer: str,
        tenant_config: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """
        Check if the answer directly addresses the query.
        """
        prompt_tmpl = self.prompts.get_prompt("relevance_judge")
        prompt = prompt_tmpl.format(query=query, answer=answer)

        from src.shared.kernel.runtime import get_settings
        from src.core.generation.application.llm_steps import resolve_llm_step_config
        from src.core.generation.domain.ports.provider_factory import get_provider_factory
        from src.core.generation.domain.provider_models import ProviderTier

        settings = get_settings()
        tenant_config = tenant_config or {}
        llm_cfg = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="admin.judge_relevance",
            settings=settings,
        )

        provider = self.llm
        try:
            provider = get_provider_factory().get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
        except Exception as e:
            logger.debug(f"Failed to resolve provider override for judge: {e}")

        kwargs: dict[str, Any] = {}
        if llm_cfg.temperature is not None:
            kwargs["temperature"] = llm_cfg.temperature
        if llm_cfg.seed is not None:
            kwargs["seed"] = llm_cfg.seed
        if llm_cfg.model is not None:
            kwargs["model"] = llm_cfg.model

        res = await provider.generate(prompt=prompt, **kwargs)
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
