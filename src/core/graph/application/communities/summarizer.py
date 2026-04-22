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
from src.shared.provider_models import RateLimitError

logger = logging.getLogger(__name__)


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
        data = await self._fetch_community_data(community_id, tenant_id)
        if not data["entities"] and not data["child_summaries"]:
            logger.warning(f"Community {community_id} has no entities and no child summaries. Skipping.")
            return {}

        # 2. Format for LLM
        entities_str = self._format_entities(data["entities"])
        relationships_str = self._format_relationships(data["relationships"])
        text_units_str = self._format_text_units(data.get("text_units", []))

        # If it's a higher level community, we might want to include summaries of child communities
        if data["child_summaries"]:
            child_summaries_str = "\n".join(
                [f"- {s['title']}: {s['summary']}" for s in data["child_summaries"]]
            )
            entities_str += f"\n\nCHILD COMMUNITIES SUMMARIES:\n{child_summaries_str}"

        prompt = COMMUNITY_SUMMARY_USER_PROMPT.format(
            entities=entities_str, relationships=relationships_str, text_units=text_units_str
        )

        # 3. Call LLM
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

            llm = self.factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )

            # NOTE: Ollama Cloud (OpenAI-compatible) can 500 on larger prompts if max_tokens is omitted.
            # Community summaries are small JSON; cap the completion to a sane budget.
            result = await llm.generate(
                prompt=prompt,
                system_prompt=COMMUNITY_SUMMARY_SYSTEM_PROMPT,
                temperature=llm_cfg.temperature,
                max_tokens=800,
                seed=llm_cfg.seed,
                work_class="communities",
            )

            # 4. Parse JSON
            summary_content = self._parse_json(result.text)

            # 5. Persist back to Neo4j
            await self._persist_summary(community_id, summary_content, tenant_id)

            return summary_content

        except RateLimitError as e:
            # Do not mark as failed; caller may retry with lower concurrency.
            logger.warning(f"Rate limited while summarizing community {community_id}: {e}")
            raise

        except Exception as e:
            logger.error(f"Failed to summarize community {community_id}: {e}")
            # Set a failure status on the node
            await self.graph.execute_write(
                "MATCH (c:Community {id: $id, tenant_id: $tenant_id}) SET c.status = 'failed', c.error = $error",
                {"id": community_id, "tenant_id": tenant_id, "error": str(e)},
            )
            return {}

    async def summarize_all_stale(
        self,
        tenant_id: str,
        batch_size: int = 50,
        concurrency: int = 1,
        tenant_config: dict[str, Any] | None = None,
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
          AND (c.summary IS NULL OR c.is_stale = true)
        RETURN c.id as id, coalesce(c.level, 0) as level
        ORDER BY c.level ASC
        """
        results = await self.graph.execute_read(query, {"tenant_id": tenant_id})

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
            )

    async def _process_community_batch(
        self,
        community_ids: list[str],
        tenant_id: str,
        batch_size: int,
        concurrency: int,
        tenant_config: dict[str, Any] | None = None,
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
                        await self.summarize_community(cid, tenant_id, tenant_config)
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

    async def _fetch_community_data(self, community_id: str, tenant_id: str) -> dict[str, Any]:
        """
        Fetches entities, relationships, child community summaries, and exemplar text units.
        """
        # Fetch entities directly belonging to this community
        entity_query = """
        MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {id: $id, tenant_id: $tenant_id})
        RETURN e.name as name, e.type as type, e.description as description
        """

        # Fetch relationships between entities in this community
        rel_query = """
        MATCH (e1:Entity)-[:BELONGS_TO]->(c:Community {id: $id, tenant_id: $tenant_id}),
              (e2:Entity)-[:BELONGS_TO]->(c),
              (e1)-[r]->(e2)
        WHERE NOT type(r) IN ['BELONGS_TO', 'PARENT_OF']
        RETURN e1.name as source, e2.name as target, type(r) as type, r.description as description
        """

        # Fetch child community summaries (if any)
        child_query = """
        MATCH (child:Community)-[:PARENT_OF]-(c:Community {id: $id, tenant_id: $tenant_id})
        WHERE child.summary IS NOT NULL
        RETURN child.title as title, child.summary as summary
        """

        # Fetch Exemplar TextUnits (Chunks)
        # We find chunks that MENTION entities in this community.
        # We limit to top 10 distinct chunks to avoid blowing up context window.
        chunk_query = """
        MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {id: $id, tenant_id: $tenant_id})
        MATCH (c_chunk:Chunk)-[:MENTIONS]->(e)
        WITH DISTINCT c_chunk LIMIT 3
        RETURN c_chunk.id as id, c_chunk.content as content
        """

        params = {"id": community_id, "tenant_id": tenant_id}
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

    def _format_entities(self, entities: list[dict[str, Any]]) -> str:
        return "\n".join([f"- {e['name']} ({e['type']}): {e['description']}" for e in entities])

    def _format_relationships(self, relationships: list[dict[str, Any]]) -> str:
        return "\n".join(
            [
                f"- {r['source']} -> {r['type']} -> {r['target']}: {r['description']}"
                for r in relationships
            ]
        )

    def _format_text_units(self, text_units: list[dict[str, Any]]) -> str:
        if not text_units:
            return "(No exemplar text units available)"
        return "\n".join([f"--- TextUnit ID: {tu['id']} ---\n{tu['content']}" for tu in text_units])

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

    async def _persist_summary(self, community_id: str, summary: dict[str, Any], tenant_id: str = ""):
        """Updates the Community node with the generated summary fields."""
        query = """
        MATCH (c:Community {id: $id, tenant_id: $tenant_id})
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
