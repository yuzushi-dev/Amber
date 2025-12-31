import logging
from typing import List, Dict, Any

from src.core.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

class CommunityLifecycleManager:
    """
    Manages the lifecycle of communities: staleness, versioning, and cleanup.
    """

    def __init__(self, neo4j_client: Neo4jClient):
        self.neo4j = neo4j_client

    async def mark_stale_by_entities(self, entity_ids: List[str]):
        """
        Marks communities as stale if they contain any of the given entity IDs.
        """
        if not entity_ids:
            return

        query = """
        MATCH (e:Entity)-[:BELONGS_TO]->(c:Community)
        WHERE e.id IN $entity_ids
        SET c.is_stale = true, c.updated_at = datetime()
        RETURN count(DISTINCT c) as count
        """
        result = await self.neo4j.execute_write(query, {"entity_ids": entity_ids})
        count = result[0]["count"] if result else 0
        if count > 0:
            logger.info(f"Marked {count} communities as stale due to entity changes")

    async def mark_stale_by_entities_by_name(self, entity_names: List[str], tenant_id: str):
        """
        Marks communities as stale if they contain any of the given entity names.
        """
        if not entity_names:
            return

        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})-[:BELONGS_TO]->(c:Community)
        WHERE e.name IN $names
        SET c.is_stale = true, c.updated_at = datetime()
        RETURN count(DISTINCT c) as count
        """
        result = await self.neo4j.execute_write(query, {"names": entity_names, "tenant_id": tenant_id})
        count = result[0]["count"] if result else 0
        if count > 0:
            logger.info(f"Marked {count} communities for tenant {tenant_id} as stale due to entity changes")

    async def mark_stale_by_tenant(self, tenant_id: str):
        """
        Marks all communities for a tenant as stale.
        """
        query = """
        MATCH (c:Community {tenant_id: $tenant_id})
        SET c.is_stale = true, c.updated_at = datetime()
        """
        await self.neo4j.execute_write(query, {"tenant_id": tenant_id})
        logger.info(f"Marked all communities for tenant {tenant_id} as stale")

    async def cleanup_orphans(self, tenant_id: str):
        """
        Finds entities without communities and assigns them to a 'Misc' community.
        """
        # 1. Find entities without BELONGS_TO
        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})
        WHERE NOT (e)-[:BELONGS_TO]->(:Community)
        RETURN e.id as id
        """
        results = await self.neo4j.execute_read(query, {"tenant_id": tenant_id})
        if not results:
            return

        entity_ids = [r["id"] for r in results]
        logger.info(f"Found {len(entity_ids)} orphaned entities for tenant {tenant_id}")

        # 2. Get or create 'Misc' community at Level 0
        misc_query = """
        MERGE (c:Community {id: 'comm_0_misc', tenant_id: $tenant_id})
        ON CREATE SET 
            c.title = 'Uncategorized Entities',
            c.level = 0,
            c.summary = 'Miscellaneous entities that do not belong to a specific cluster.',
            c.status = 'ready'
        RETURN c.id as id
        """
        await self.neo4j.execute_write(misc_query, {"tenant_id": tenant_id})

        # 3. Link orphans
        link_query = """
        MATCH (e:Entity {tenant_id: $tenant_id}), (c:Community {id: 'comm_0_misc', tenant_id: $tenant_id})
        WHERE e.id IN $entity_ids
        MERGE (e)-[:BELONGS_TO]->(c)
        """
        await self.neo4j.execute_write(link_query, {"tenant_id": tenant_id, "entity_ids": entity_ids})
        logger.info(f"Assigned {len(entity_ids)} entities to 'Misc' community")

    async def get_community_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Returns stats about communities for a tenant."""
        query = """
        MATCH (c:Community {tenant_id: $tenant_id})
        RETURN 
            count(c) as total,
            sum(case when c.is_stale then 1 else 0 end) as stale,
            sum(case when c.status = 'ready' then 1 else 0 end) as ready,
            sum(case when c.status = 'failed' then 1 else 0 end) as failed,
            max(c.level) as max_level
        """
        results = await self.neo4j.execute_read(query, {"tenant_id": tenant_id})
        if not results:
            return {"total": 0}
        return results[0]
