import asyncio
import json
import logging
import re
from typing import Any

from src.core.graph.neo4j_client import Neo4jClient
from src.core.prompts.community_summary import (
    COMMUNITY_SUMMARY_SYSTEM_PROMPT,
    COMMUNITY_SUMMARY_USER_PROMPT,
)
from src.core.providers.base import ProviderTier
from src.core.providers.factory import ProviderFactory

logger = logging.getLogger(__name__)

class CommunitySummarizer:
    """
    Generates structured reports for communities using LLMs.
    """

    def __init__(self, neo4j_client: Neo4jClient, provider_factory: ProviderFactory):
        self.neo4j = neo4j_client
        self.factory = provider_factory
        # Use Economy tier for summarization as it's often a high-volume task
        self.llm = self.factory.get_llm_provider(tier=ProviderTier.ECONOMY)

    async def summarize_community(self, community_id: str, tenant_id: str) -> dict[str, Any]:
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
        if not data["entities"] and not data["child_communities"]:
            logger.warning(f"Community {community_id} has no members. Skipping.")
            return {}

        # 2. Format for LLM
        entities_str = self._format_entities(data["entities"])
        relationships_str = self._format_relationships(data["relationships"])
        text_units_str = self._format_text_units(data.get("text_units", []))

        # If it's a higher level community, we might want to include summaries of child communities
        if data["child_summaries"]:
            child_summaries_str = "\n".join([f"- {s['title']}: {s['summary']}" for s in data["child_summaries"]])
            entities_str += f"\n\nCHILD COMMUNITIES SUMMARIES:\n{child_summaries_str}"

        prompt = COMMUNITY_SUMMARY_USER_PROMPT.format(
            entities=entities_str,
            relationships=relationships_str,
            text_units=text_units_str
        )

        # 3. Call LLM
        try:
            result = await self.llm.generate(
                prompt=prompt,
                system_prompt=COMMUNITY_SUMMARY_SYSTEM_PROMPT,
                temperature=0.3
            )

            # 4. Parse JSON
            summary_content = self._parse_json(result.text)

            # 5. Persist back to Neo4j
            await self._persist_summary(community_id, summary_content)

            return summary_content

        except Exception as e:
            logger.error(f"Failed to summarize community {community_id}: {e}")
            # Set a failure status on the node
            await self.neo4j.execute_write(
                "MATCH (c:Community {id: $id}) SET c.status = 'failed', c.error = $error",
                {"id": community_id, "error": str(e)}
            )
            return {}

    async def summarize_all_stale(self, tenant_id: str, batch_size: int = 10):
        """
        Finds all communities marked as stale (or missing summary) and summarizes them.
        """
        query = """
        MATCH (c:Community)
        WHERE c.tenant_id = $tenant_id
          AND (c.summary IS NULL OR c.is_stale = true)
        RETURN c.id as id
        ORDER BY c.level ASC
        """
        results = await self.neo4j.execute_read(query, {"tenant_id": tenant_id})

        community_ids = [r["id"] for r in results]
        logger.info(f"Found {len(community_ids)} communities needing summarization for tenant {tenant_id}")

        # Group by level to ensure child communities are summarized before parents
        # Actually our query already orders by level ASC

        for i in range(0, len(community_ids), batch_size):
            batch = community_ids[i:i+batch_size]
            tasks = [self.summarize_community(cid, tenant_id) for cid in batch]
            await asyncio.gather(*tasks)

    async def _fetch_community_data(self, community_id: str, tenant_id: str) -> dict[str, Any]:
        """
        Fetches entities, relationships, child community summaries, and exemplar text units.
        """
        # Fetch entities directly belonging to this community
        entity_query = """
        MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {id: $id})
        RETURN e.name as name, e.type as type, e.description as description
        """

        # Fetch relationships between entities in this community
        rel_query = """
        MATCH (e1:Entity)-[:BELONGS_TO]->(c:Community {id: $id}),
              (e2:Entity)-[:BELONGS_TO]->(c),
              (e1)-[r]->(e2)
        WHERE NOT type(r) IN ['BELONGS_TO', 'PARENT_OF']
        RETURN e1.name as source, e2.name as target, type(r) as type, r.description as description
        """

        # Fetch child community summaries (if any)
        child_query = """
        MATCH (child:Community)-[:PARENT_OF]-(c:Community {id: $id})
        WHERE child.summary IS NOT NULL
        RETURN child.title as title, child.summary as summary
        """

        # Fetch Exemplar TextUnits (Chunks)
        # We find chunks that MENTION entities in this community.
        # We limit to top 10 distinct chunks to avoid blowing up context window.
        chunk_query = """
        MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {id: $id})
        MATCH (c_chunk:Chunk)-[:MENTIONS]->(e)
        WITH DISTINCT c_chunk LIMIT 10
        RETURN c_chunk.id as id, c_chunk.content as content
        """

        entities = await self.neo4j.execute_read(entity_query, {"id": community_id})
        relationships = await self.neo4j.execute_read(rel_query, {"id": community_id})
        child_summaries = await self.neo4j.execute_read(child_query, {"id": community_id})
        text_units = await self.neo4j.execute_read(chunk_query, {"id": community_id})

        return {
            "entities": entities,
            "relationships": relationships,
            "child_summaries": child_summaries,
            "text_units": text_units,
            "child_communities": []
        }

    def _format_entities(self, entities: list[dict[str, Any]]) -> str:
        return "\n".join([f"- {e['name']} ({e['type']}): {e['description']}" for e in entities])

    def _format_relationships(self, relationships: list[dict[str, Any]]) -> str:
        return "\n".join([f"- {r['source']} -> {r['type']} -> {r['target']}: {r['description']}" for r in relationships])

    def _format_text_units(self, text_units: list[dict[str, Any]]) -> str:
        if not text_units:
            return "(No exemplar text units available)"
        return "\n".join([
            f"--- TextUnit ID: {tu['id']} ---\n{tu['content']}"
            for tu in text_units
        ])

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
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON block with regex
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            raise

    async def _persist_summary(self, community_id: str, summary: dict[str, Any]):
        """Updates the Community node with the generated summary fields."""
        query = """
        MATCH (c:Community {id: $id})
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
            "title": summary.get("title", "Untitled Community"),
            "summary": summary.get("summary", ""),
            "rating": summary.get("rating", 0),
            "key_entities": summary.get("key_entities", []),
            "findings": summary.get("findings", [])
        }
        await self.neo4j.execute_write(query, params)
