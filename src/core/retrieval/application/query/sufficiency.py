"""
Sufficient Context Evaluator
============================

Quality-control gate for iterative retrieval (agentic RAG). After an initial
search, an LLM judges whether the retrieved snippets are sufficient to answer
the query. When not, it emits targeted "gap" follow-up queries that drive an
additional retrieval round — mirroring the Sufficient Context Agent pattern
(evaluate snippets -> identify gaps -> re-retrieve).

Fails open: any error yields a "sufficient" verdict so the gate never blocks a
response.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.generation.application.prompts.query_analysis import QUERY_SUFFICIENCY_PROMPT
from src.core.generation.domain.ports.provider_factory import (
    ProviderFactoryPort,
    build_provider_factory,
    get_provider_factory,
)
from src.core.generation.domain.ports.providers import LLMProviderPort
from src.core.generation.domain.provider_models import ProviderTier

logger = logging.getLogger(__name__)

# Cap how much of each snippet is shown to the judge to bound token cost.
_SNIPPET_CHAR_LIMIT = 600
_MAX_SNIPPETS_IN_PROMPT = 12


@dataclass
class SufficiencyVerdict:
    """Outcome of a sufficiency evaluation."""

    is_sufficient: bool
    reason: str = ""
    gap_queries: list[str] = field(default_factory=list)


class SufficiencyEvaluator:
    """
    Evaluates whether retrieved chunks are sufficient to answer a query and,
    if not, proposes targeted follow-up queries to fill the gaps.
    """

    def __init__(
        self,
        provider: LLMProviderPort | None = None,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        provider_factory: ProviderFactoryPort | None = None,
    ):
        if provider_factory:
            self.factory = provider_factory
        else:
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
            if openai_api_key or anthropic_api_key or settings.ollama_base_url:
                self.factory = build_provider_factory(
                    openai_api_key=openai_api_key,
                    anthropic_api_key=anthropic_api_key,
                    ollama_base_url=settings.ollama_base_url,
                )
            else:
                self.factory = get_provider_factory()

        if provider:
            self.provider = provider
        else:
            self.provider = self.factory.get_llm_provider(model_tier="economy")

    async def evaluate(
        self,
        query: str,
        chunks: list[dict],
        max_gap_queries: int = 3,
        tenant_config: dict | None = None,
        tried_gap_queries: list[str] | None = None,
        draft_answer: str | None = None,
    ) -> SufficiencyVerdict:
        """
        Judge sufficiency of `chunks` for `query`.

        Args:
            query: The (already rewritten) user query.
            chunks: Retrieved chunk dicts with a "content" key.
            max_gap_queries: Hard cap on proposed follow-up queries.
            tenant_config: Tenant LLM config for provider/model resolution.
            tried_gap_queries: Gap queries already attempted in prior rounds. The
                judge is told not to repeat them — avoids wasted re-retrieval
                rounds proposing identical gaps (progressive feedback).
            draft_answer: Optional intermediate draft answer. When provided, the
                judge also evaluates the draft against the query (not just the
                snippets), catching gaps that raw snippets alone do not reveal.

        Returns:
            SufficiencyVerdict. On any failure, returns is_sufficient=True
            (fail open) so retrieval proceeds without an extra round.
        """
        if not chunks:
            # Nothing retrieved — a gap is certain; ask to retry with the query.
            return SufficiencyVerdict(
                is_sufficient=False,
                reason="No chunks retrieved.",
                gap_queries=[query],
            )

        snippets = self._format_snippets(chunks)
        prompt = QUERY_SUFFICIENCY_PROMPT.format(
            query=query,
            snippets=snippets,
            max_gap_queries=max_gap_queries,
            tried_block=self._tried_block(tried_gap_queries),
            draft_block=self._draft_block(draft_answer),
        )

        try:
            from src.core.generation.application.llm_steps import resolve_llm_step_config
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
            tenant_config = tenant_config or {}

            res_ollama_url = tenant_config.get("ollama_base_url")
            scoped_factory = self.factory
            if res_ollama_url and res_ollama_url != settings.ollama_base_url:
                scoped_factory = build_provider_factory(
                    openai_api_key=settings.openai_api_key,
                    anthropic_api_key=settings.anthropic_api_key,
                    ollama_base_url=res_ollama_url,
                )

            llm_cfg = resolve_llm_step_config(
                tenant_config=tenant_config,
                step_id="retrieval.sufficiency_check",
                settings=settings,
            )
            provider = scoped_factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
            kwargs: dict[str, Any] = {}
            if llm_cfg.temperature is not None:
                kwargs["temperature"] = llm_cfg.temperature
            if llm_cfg.seed is not None:
                kwargs["seed"] = llm_cfg.seed

            response_res = await provider.generate(prompt, work_class="chat", **kwargs)
            return self._parse(response_res.text or "", max_gap_queries)

        except Exception as e:
            logger.error(f"Sufficiency evaluation failed (failing open): {e}")
            return SufficiencyVerdict(is_sufficient=True, reason="evaluation_error")

    def _tried_block(self, tried_gap_queries: list[str] | None) -> str:
        tried = [q.strip() for q in (tried_gap_queries or []) if q and q.strip()]
        if not tried:
            return ""
        listed = "\n".join(f"  - {q}" for q in tried[:12])
        return (
            "- These follow-up queries were ALREADY attempted in earlier rounds and "
            "returned no new useful information. Do NOT propose them or close paraphrases "
            "again. Propose genuinely DIFFERENT angles; if no new angle exists, return "
            "sufficient=true with an empty gap_queries list:\n"
            f"{listed}\n"
        )

    def _draft_block(self, draft_answer: str | None) -> str:
        draft = (draft_answer or "").strip()
        if not draft:
            return ""
        if len(draft) > 2000:
            draft = draft[:2000] + "…"
        return (
            "\n### Draft answer under review\n"
            "Also evaluate this DRAFT answer against the query: if it leaves required "
            "parts of the query unanswered, or makes claims not supported by the snippets, "
            "mark NOT sufficient and target the missing/unsupported aspects with gap_queries.\n"
            f'"""\n{draft}\n"""\n'
        )

    def _format_snippets(self, chunks: list[dict]) -> str:
        lines = []
        for i, c in enumerate(chunks[:_MAX_SNIPPETS_IN_PROMPT], start=1):
            content = (c.get("content") or "").strip().replace("\n", " ")
            if len(content) > _SNIPPET_CHAR_LIMIT:
                content = content[:_SNIPPET_CHAR_LIMIT] + "…"
            lines.append(f"[{i}] {content}")
        return "\n".join(lines)

    def _parse(self, raw: str, max_gap_queries: int) -> SufficiencyVerdict:
        response = raw.strip()
        if "```json" in response:
            response = response.split("```json")[-1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[-1].split("```")[0].strip()

        # Be tolerant: extract the first {...} block if the model added prose.
        if not response.startswith("{"):
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1 and end > start:
                response = response[start : end + 1]

        try:
            data = json.loads(response)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Sufficiency verdict not parseable (failing open): %r", raw[:200])
            return SufficiencyVerdict(is_sufficient=True, reason="unparseable")

        is_sufficient = bool(data.get("sufficient", True))
        reason = str(data.get("reason", "") or "")
        gap_queries_raw = data.get("gap_queries") or []
        if not isinstance(gap_queries_raw, list):
            gap_queries_raw = []
        gap_queries = [str(g).strip() for g in gap_queries_raw if str(g).strip()][:max_gap_queries]

        # If judged insufficient but no actionable gaps were given, treat as
        # sufficient to avoid a wasted retrieval round.
        if not is_sufficient and not gap_queries:
            return SufficiencyVerdict(
                is_sufficient=True, reason=reason or "no_gap_queries"
            )

        return SufficiencyVerdict(
            is_sufficient=is_sufficient, reason=reason, gap_queries=gap_queries
        )
