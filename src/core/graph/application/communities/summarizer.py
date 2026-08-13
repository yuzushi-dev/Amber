import asyncio
import json
import logging
import re
from typing import Any

from src.core.generation.application.prompts.community_summary import (
    COMMUNITY_SUMMARY_SYSTEM_PROMPT,
    COMMUNITY_SUMMARY_USER_PROMPT,
)
from src.core.generation.domain.ports.provider_factory import ProviderFactoryPort
from src.core.generation.domain.provider_models import ProviderTier
from src.core.graph.domain.ports.graph_client import GraphClientPort
from src.core.utils.tokenizer import Tokenizer
from src.shared.model_registry import llm_context_window
from src.shared.provider_models import RateLimitError

logger = logging.getLogger(__name__)

SUMMARY_COMPLETION_TOKENS = 800
SUMMARY_PROVIDER_OVERHEAD_TOKENS = 512
SUMMARY_BUDGET_MARGIN_TOKENS = 512
MAX_ENTITY_DESCRIPTION_TOKENS = 128
MAX_RELATIONSHIP_DESCRIPTION_TOKENS = 96
MAX_TEXT_UNIT_TOKENS = 512
MAX_CHILD_SUMMARY_TOKENS = 256


class CommunityPromptBudgetError(ValueError):
    """Raised when a community cannot be represented within the model context window."""


class CommunitySummarizer:
    """
    Generates structured reports for communities using LLMs.
    """

    def __init__(self, graph_client: GraphClientPort, provider_factory: ProviderFactoryPort):
        self.graph = graph_client
        self.factory = provider_factory

    async def summarize_community(
        self,
        community_id: str,
        tenant_id: str,
        tenant_config: dict[str, Any] | None = None,
        generation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Generates a summary for a single community.

        Args:
            community_id: The ID of the community (comm_...)
            tenant_id: The tenant ID for isolation.

        Returns:
            Dict containing the structured summary.
        """
        logger.info(f"Summarizing community {community_id} for tenant {tenant_id}")

        # 1. Fetch data for community
        data = await self._fetch_community_data(community_id, tenant_id, generation_id)
        if not data["entities"] and not data["child_summaries"]:
            logger.warning(
                f"Community {community_id} has no entities and no child summaries. Skipping."
            )
            return {}

        # 2. Resolve the target model before rendering so the input has a hard budget.
        try:
            from src.core.generation.application.llm_steps import resolve_llm_step_config
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
            tenant_config = tenant_config or {}
            llm_cfg = resolve_llm_step_config(
                tenant_config=tenant_config,
                step_id="graph.community_summary",
                settings=settings,
            )
            # Resolve the primary provider without its wrapper to obtain the
            # canonical provider/model used to budget the prompt.
            budget_llm = self.factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
                with_failover=False,
            )
            primary_budget_llm = (
                budget_llm.providers[0] if getattr(budget_llm, "providers", None) else budget_llm
            )
            prompt = self._build_prompt(
                data,
                provider=llm_cfg.provider or primary_budget_llm.provider_name,
                model=llm_cfg.model or primary_budget_llm.default_model,
            )
            llm = self.factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )

            result = await llm.generate(
                prompt=prompt,
                system_prompt=COMMUNITY_SUMMARY_SYSTEM_PROMPT,
                temperature=llm_cfg.temperature,
                max_tokens=SUMMARY_COMPLETION_TOKENS,
                seed=llm_cfg.seed,
                work_class="communities",
            )

            # 4. Parse JSON
            summary_content = self._parse_json(result.text)

            # 5. Persist back to Neo4j
            await self._persist_summary(community_id, summary_content, tenant_id, generation_id)

            return summary_content

        except RateLimitError as e:
            # Do not mark as failed; caller may retry with lower concurrency.
            logger.warning(f"Rate limited while summarizing community {community_id}: {e}")
            raise

        except Exception as e:
            logger.error(f"Failed to summarize community {community_id}: {e}")
            # Keep a previously published summary queryable when a later refresh fails.
            # A new summary is only promoted by _persist_summary after successful generation.
            await self.graph.execute_write(
                """
                MATCH (c:Community {id: $id, tenant_id: $tenant_id})
                WHERE $generation_id IS NULL OR c.generation_id = $generation_id
                FOREACH (_ IN CASE WHEN c.summary IS NOT NULL THEN [1] ELSE [] END |
                    SET c.status = 'ready', c.is_stale = true, c.error = $error
                )
                FOREACH (_ IN CASE WHEN c.summary IS NULL THEN [1] ELSE [] END |
                    SET c.status = 'failed', c.error = $error
                )
                """,
                {
                    "id": community_id,
                    "tenant_id": tenant_id,
                    "generation_id": generation_id,
                    "error": str(e),
                },
            )
            return {}

    async def summarize_all_stale(
        self,
        tenant_id: str,
        batch_size: int = 50,
        concurrency: int = 1,
        tenant_config: dict[str, Any] | None = None,
        generation_id: str | None = None,
    ):
        """
        Finds all communities marked as stale (or missing summary) and summarizes them.

        If the LLM provider rate-limits (HTTP 429 surfaced as RateLimitError), we:
        - retry those communities in the next batch
        - optionally reduce concurrency by 1 when rate limiting is significant
        """
        # 1. Fetch candidate IDs, grouped by level.
        # Level 0 communities have direct entity members.
        # Level 1+ communities only have child community summaries.
        # We MUST process level 0 first so child summaries exist when level 1+ is processed.
        query = """
        MATCH (c:Community)
        WHERE c.tenant_id = $tenant_id
          AND ($generation_id IS NULL OR c.generation_id = $generation_id)
          AND ($generation_id IS NOT NULL OR coalesce(c.active, true) = true)
          AND (c.summary IS NULL OR c.is_stale = true)
        RETURN c.id as id, coalesce(c.level, 0) as level
        ORDER BY c.level ASC
        """
        results = await self.graph.execute_read(
            query, {"tenant_id": tenant_id, "generation_id": generation_id}
        )

        level_0_ids = [r["id"] for r in results if r["level"] == 0]
        higher_level_ids = [r["id"] for r in results if r["level"] > 0]
        total = len(level_0_ids) + len(higher_level_ids)
        current_concurrency = max(1, int(concurrency))
        logger.info(
            f"Found {total} communities needing summarization for tenant {tenant_id} "
            f"(level 0: {len(level_0_ids)}, level 1+: {len(higher_level_ids)}). "
            f"Concurrency: {current_concurrency}"
        )

        if not total:
            return

        # Process in two passes: level 0 first, then level 1+
        for pass_label, community_ids in [("level 0", level_0_ids), ("level 1+", higher_level_ids)]:
            if not community_ids:
                logger.info(f"No {pass_label} communities to summarize. Skipping pass.")
                continue
            logger.info(f"Starting {pass_label} pass: {len(community_ids)} communities")
            await self._process_community_batch(
                community_ids=community_ids,
                tenant_id=tenant_id,
                batch_size=batch_size,
                concurrency=current_concurrency,
                tenant_config=tenant_config,
                generation_id=generation_id,
            )

    async def _process_community_batch(
        self,
        community_ids: list[str],
        tenant_id: str,
        batch_size: int,
        concurrency: int,
        tenant_config: dict[str, Any] | None = None,
        generation_id: str | None = None,
    ):
        """Process a list of community IDs in batches with rate-limit handling."""
        from collections import deque

        # "Many 429s" threshold: reduce concurrency by 1 for the NEXT batch.
        rate_limit_reduce_ratio = 0.10
        rate_limit_reduce_min = 2

        # Avoid infinite loops if the provider is saturated; leave as stale for next run.
        max_rate_limit_retries_per_community = 5
        rate_limit_retries: dict[str, int] = {}

        carry_over: deque[str] = deque()
        cursor = 0
        total = len(community_ids)
        batch_num = 0
        current_concurrency = max(1, concurrency)

        while cursor < total or carry_over:
            batch_num += 1

            # Build next batch: retry rate-limited communities first, then take new IDs.
            batch_ids: list[str] = []
            while carry_over and len(batch_ids) < batch_size:
                batch_ids.append(carry_over.popleft())

            remaining = batch_size - len(batch_ids)
            if remaining > 0 and cursor < total:
                batch_ids.extend(community_ids[cursor : cursor + remaining])
                cursor += remaining

            if not batch_ids:
                break

            logger.info(
                f"Processing batch {batch_num}: {len(batch_ids)} communities "
                f"(cursor={cursor}/{total}, carry_over={len(carry_over)}, concurrency={current_concurrency})"
            )

            sem = asyncio.Semaphore(current_concurrency)

            async def _bounded_summarize(cid: str, _sem=sem):
                async with _sem:
                    try:
                        await self.summarize_community(cid, tenant_id, tenant_config, generation_id)
                        return ("ok", cid, None)
                    except RateLimitError as e:
                        return ("rate_limited", cid, e)
                    except Exception as e:
                        # summarize_community handles most errors; this is a safety net.
                        logger.error(f"Unhandled exception while summarizing community {cid}: {e}")
                        return ("error", cid, e)

            results = await asyncio.gather(*[_bounded_summarize(cid) for cid in batch_ids])

            rate_limited = [(cid, err) for (kind, cid, err) in results if kind == "rate_limited"]
            if not rate_limited:
                continue

            # Requeue rate-limited items so they get retried in the next batch.
            for cid, _err in rate_limited:
                attempts = rate_limit_retries.get(cid, 0) + 1
                rate_limit_retries[cid] = attempts
                if attempts <= max_rate_limit_retries_per_community:
                    carry_over.append(cid)
                else:
                    logger.warning(
                        f"Community {cid} hit rate limit {attempts} times; leaving it stale for next run"
                    )

            rl_count = len(rate_limited)
            rl_ratio = rl_count / max(1, len(batch_ids))

            if (
                current_concurrency > 1
                and rl_count >= rate_limit_reduce_min
                and rl_ratio >= rate_limit_reduce_ratio
            ):
                current_concurrency -= 1
                logger.warning(
                    f"Rate limits in batch {batch_num}: {rl_count}/{len(batch_ids)}. "
                    f"Reducing concurrency to {current_concurrency} for next batch"
                )

    async def _fetch_community_data(
        self, community_id: str, tenant_id: str, generation_id: str | None = None
    ) -> dict[str, Any]:
        """
        Fetches entities, relationships, child community summaries, and exemplar text units.
        """
        # Fetch entities directly belonging to this community
        entity_query = """
        MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {id: $id, tenant_id: $tenant_id})
        WHERE $generation_id IS NULL OR c.generation_id = $generation_id
        RETURN e.name as name, e.type as type, e.description as description
        """

        # Fetch relationships between entities in this community
        rel_query = """
        MATCH (e1:Entity)-[:BELONGS_TO]->(c:Community {id: $id, tenant_id: $tenant_id}),
              (e2:Entity)-[:BELONGS_TO]->(c),
              (e1)-[r]->(e2)
        WHERE ($generation_id IS NULL OR c.generation_id = $generation_id)
          AND NOT type(r) IN ['BELONGS_TO', 'PARENT_OF']
        RETURN e1.name as source, e2.name as target, type(r) as type, r.description as description
        """

        # Fetch child community summaries (if any)
        child_query = """
        MATCH (child:Community)-[:PARENT_OF]-(c:Community {id: $id, tenant_id: $tenant_id})
        WHERE child.summary IS NOT NULL
          AND ($generation_id IS NULL OR c.generation_id = $generation_id)
          AND ($generation_id IS NULL OR child.generation_id = $generation_id)
        RETURN child.id as id, child.title as title, child.summary as summary
        ORDER BY child.id
        """

        # Fetch exemplar text units in a stable order.
        chunk_query = """
        MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {id: $id, tenant_id: $tenant_id})
        WHERE $generation_id IS NULL OR c.generation_id = $generation_id
        MATCH (c_chunk:Chunk)-[:MENTIONS]->(e)
        WITH DISTINCT c_chunk ORDER BY c_chunk.id LIMIT 3
        RETURN c_chunk.id as id, c_chunk.content as content
        """

        params = {
            "id": community_id,
            "tenant_id": tenant_id,
            "generation_id": generation_id,
        }
        entities = await self.graph.execute_read(entity_query, params)
        relationships = await self.graph.execute_read(rel_query, params)
        child_summaries = await self.graph.execute_read(child_query, params)
        text_units = await self.graph.execute_read(chunk_query, params)

        return {
            "entities": entities,
            "relationships": relationships,
            "child_summaries": child_summaries,
            "text_units": text_units,
            "child_communities": [],
        }

    def _build_prompt(self, data: dict[str, Any], *, provider: str, model: str) -> str:
        context_window = llm_context_window(provider, model)
        if context_window is None:
            raise CommunityPromptBudgetError(
                f"No context window is configured for provider={provider!r}, model={model!r}"
            )
        input_budget = context_window - SUMMARY_COMPLETION_TOKENS - SUMMARY_PROVIDER_OVERHEAD_TOKENS
        render_budget = input_budget - SUMMARY_BUDGET_MARGIN_TOKENS
        if render_budget <= 0:
            raise CommunityPromptBudgetError(
                f"Context window {context_window} cannot reserve summary completion and provider overhead"
            )

        entities = sorted(
            data["entities"],
            key=lambda entity: (
                str(entity.get("name") or ""),
                str(entity.get("type") or ""),
                str(entity.get("description") or ""),
            ),
        )
        entity_lines = [
            f"- {entity.get('name') or '(unnamed)'} ({entity.get('type') or 'Unknown'})"
            for entity in entities
        ]
        empty_tokens = self._prompt_tokens(self._render_prompt("", "", ""), model)
        if empty_tokens > render_budget:
            raise CommunityPromptBudgetError(
                f"Context window {context_window} cannot hold an empty community prompt"
            )
        # A partial roster beats a permanently failed community: keep the deterministic
        # prefix that fits. Measured on the rendered prompt, because per-line token sums
        # drift from the assembled text.
        kept = self._fit_rendered_entities(entity_lines, render_budget, model)
        if kept < len(entity_lines):
            logger.warning(
                "Community entity roster truncated to %s/%s entries to fit the %s token budget",
                kept,
                len(entity_lines),
                render_budget,
            )
            entity_lines = entity_lines[:kept]
        used_tokens = self._prompt_tokens(
            self._render_prompt("\n".join(entity_lines), "", ""), model
        )

        entity_detail_lines = [
            (
                f"- {entity.get('name') or '(unnamed)'}: "
                f"{Tokenizer.truncate_to_budget(str(entity.get('description') or ''), MAX_ENTITY_DESCRIPTION_TOKENS, model)}"
            )
            for entity in entities
            if entity.get("description")
        ]
        entity_details, used_tokens = self._fit_lines(
            "ENTITY DESCRIPTIONS:", entity_detail_lines, used_tokens, render_budget, model
        )

        relationships = sorted(
            data["relationships"],
            key=lambda relationship: (
                not bool(relationship.get("description")),
                str(relationship.get("source") or ""),
                str(relationship.get("target") or ""),
                str(relationship.get("type") or ""),
                str(relationship.get("description") or ""),
            ),
        )
        relationship_lines = [
            f"- {relationship.get('source') or '(unknown)'} -> "
            f"{relationship.get('type') or 'RELATED_TO'} -> "
            f"{relationship.get('target') or '(unknown)'}: "
            f"{Tokenizer.truncate_to_budget(str(relationship.get('description') or ''), MAX_RELATIONSHIP_DESCRIPTION_TOKENS, model)}"
            for relationship in relationships
        ]
        relationship_lines, used_tokens = self._fit_lines(
            "", relationship_lines, used_tokens, render_budget, model
        )

        text_units = sorted(
            data.get("text_units", []), key=lambda text_unit: str(text_unit.get("id") or "")
        )
        text_unit_lines = [
            f"--- TextUnit ID: {text_unit.get('id') or '(unknown)'} ---\n"
            f"{Tokenizer.truncate_to_budget(str(text_unit.get('content') or ''), MAX_TEXT_UNIT_TOKENS, model)}"
            for text_unit in text_units
        ]
        text_unit_lines, used_tokens = self._fit_lines(
            "", text_unit_lines, used_tokens, render_budget, model
        )

        child_summaries = sorted(
            data["child_summaries"],
            key=lambda child: (
                str(child.get("id") or ""),
                str(child.get("title") or ""),
                str(child.get("summary") or ""),
            ),
        )
        child_lines = [
            f"- {child.get('title') or '(untitled)'}: "
            f"{Tokenizer.truncate_to_budget(str(child.get('summary') or ''), MAX_CHILD_SUMMARY_TOKENS, model)}"
            for child in child_summaries
        ]
        child_lines, used_tokens = self._fit_lines(
            "CHILD COMMUNITIES SUMMARIES:", child_lines, used_tokens, render_budget, model
        )

        entities_str = "\n".join(
            line for group in (entity_lines, entity_details, child_lines) for line in group
        )
        prompt = self._render_prompt(
            entities_str,
            "\n".join(relationship_lines),
            "\n".join(text_unit_lines) or "(No exemplar text units available)",
        )
        actual_tokens = self._prompt_tokens(prompt, model)
        if actual_tokens > input_budget:
            raise CommunityPromptBudgetError(
                f"Community prompt requires {actual_tokens} input tokens; budget is {input_budget}"
            )
        logger.info(
            "Community prompt budget provider=%s model=%s context=%s input=%s/%s "
            "entities=%s descriptions=%s/%s relationships=%s/%s text_units=%s/%s children=%s/%s",
            provider,
            model,
            context_window,
            actual_tokens,
            input_budget,
            len(entities),
            max(0, len(entity_details) - 1),
            len(entity_detail_lines),
            len(relationship_lines),
            len(relationships),
            len(text_unit_lines),
            len(text_units),
            max(0, len(child_lines) - 1),
            len(child_summaries),
        )
        return prompt

    @staticmethod
    def _render_prompt(entities: str, relationships: str, text_units: str) -> str:
        return COMMUNITY_SUMMARY_USER_PROMPT.format(
            entities=entities,
            relationships=relationships,
            text_units=text_units,
        )

    @staticmethod
    def _prompt_tokens(prompt: str, model: str) -> int:
        return Tokenizer.count_tokens(f"{COMMUNITY_SUMMARY_SYSTEM_PROMPT}\n{prompt}", model)

    def _fit_rendered_entities(self, lines: list[str], render_budget: int, model: str) -> int:
        """Largest prefix of `lines` whose rendered prompt stays within the budget."""
        low, high = 0, len(lines)
        while low < high:
            mid = (low + high + 1) // 2
            rendered = self._render_prompt("\n".join(lines[:mid]), "", "")
            if self._prompt_tokens(rendered, model) <= render_budget:
                low = mid
            else:
                high = mid - 1
        return low

    @staticmethod
    def _fit_lines(
        heading: str,
        lines: list[str],
        used_tokens: int,
        input_budget: int,
        model: str,
    ) -> tuple[list[str], int]:
        retained: list[str] = []
        if heading:
            heading_tokens = Tokenizer.count_tokens(f"\n{heading}\n", model)
            if used_tokens + heading_tokens > input_budget or not lines:
                return retained, used_tokens
            retained.append(heading)
            used_tokens += heading_tokens
        for line in lines:
            line_tokens = Tokenizer.count_tokens(f"\n{line}", model)
            if used_tokens + line_tokens > input_budget:
                break
            retained.append(line)
            used_tokens += line_tokens
        return retained, used_tokens

    def _parse_json(self, text: str) -> dict[str, Any]:
        """Clean and parse JSON from LLM response."""
        # Remove code blocks if present
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError:
            # Try to find JSON block with regex
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                return json.loads(match.group(1), strict=False)
            raise

    async def _persist_summary(
        self,
        community_id: str,
        summary: dict[str, Any],
        tenant_id: str = "",
        generation_id: str | None = None,
    ):
        """Updates the Community node with the generated summary fields."""
        query = """
        MATCH (c:Community {id: $id, tenant_id: $tenant_id})
        WHERE $generation_id IS NULL OR c.generation_id = $generation_id
        SET c.title = $title,
            c.summary = $summary,
            c.rating = $rating,
            c.key_entities = $key_entities,
            c.findings = $findings,
            c.is_stale = false,
            c.status = 'ready',
            c.last_updated_at = datetime()
        """
        params = {
            "id": community_id,
            "tenant_id": tenant_id,
            "generation_id": generation_id,
            "title": summary.get("title", "Untitled Community"),
            "summary": summary.get("summary", ""),
            "rating": summary.get("rating", 0),
            "key_entities": [json.dumps(e) for e in summary.get("key_entities", [])]
            if summary.get("key_entities")
            else [],
            "findings": [json.dumps(f) for f in summary.get("findings", [])]
            if summary.get("findings")
            else [],
        }
        await self.graph.execute_write(query, params)
