import logging
from typing import Any

from src.core.graph.domain.ports.graph_client import GraphClientPort

logger = logging.getLogger(__name__)


class CommunityLifecycleManager:
    """
    Manages the lifecycle of communities: staleness, versioning, and cleanup.
    """

    def __init__(self, graph_client: GraphClientPort):
        self.graph = graph_client

    async def mark_stale_by_entities(self, entity_names: list[str], tenant_id: str):
        """
        Marks communities as stale if they contain any of the given entity names.

        NOTE: :Entity nodes have no ``id`` property; identity is (name, tenant_id).
        This method is equivalent to ``mark_stale_by_entities_by_name`` and delegates
        to it so there is a single implementation.
        """
        await self.mark_stale_by_entities_by_name(entity_names, tenant_id)

    async def mark_stale_by_entities_by_name(self, entity_names: list[str], tenant_id: str):
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
        result = await self.graph.execute_write(
            query, {"names": entity_names, "tenant_id": tenant_id}
        )
        count = result[0]["count"] if result else 0
        if count > 0:
            logger.info(
                f"Marked {count} communities for tenant {tenant_id} as stale due to entity changes"
            )

    async def mark_stale_by_tenant(self, tenant_id: str):
        """
        Marks all communities for a tenant as stale.
        """
        query = """
        MATCH (c:Community {tenant_id: $tenant_id})
        SET c.is_stale = true, c.updated_at = datetime()
        """
        await self.graph.execute_write(query, {"tenant_id": tenant_id})
        logger.info(f"Marked all communities for tenant {tenant_id} as stale")

    async def cleanup_orphans(self, tenant_id: str):
        """
        Finds entities without communities and assigns them to a 'Misc' community.
        """
        # 1. Find entities without BELONGS_TO — key on (name, tenant_id), not e.id
        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})
        WHERE NOT (e)-[:BELONGS_TO]->(:Community)
        RETURN e.name as name
        """
        results = await self.graph.execute_read(query, {"tenant_id": tenant_id})
        if not results:
            return

        entity_names = [r["name"] for r in results]
        logger.info(f"Found {len(entity_names)} orphaned entities for tenant {tenant_id}")

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
        await self.graph.execute_write(misc_query, {"tenant_id": tenant_id})

        # 3. Link orphans — match on (name, tenant_id) since :Entity has no id property
        link_query = """
        MATCH (e:Entity {tenant_id: $tenant_id}), (c:Community {id: 'comm_0_misc', tenant_id: $tenant_id})
        WHERE e.name IN $entity_names
        MERGE (e)-[:BELONGS_TO]->(c)
        """
        await self.graph.execute_write(
            link_query, {"tenant_id": tenant_id, "entity_names": entity_names}
        )
        logger.info(f"Assigned {len(entity_names)} entities to 'Misc' community")

    async def get_community_stats(self, tenant_id: str) -> dict[str, Any]:
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
        results = await self.graph.execute_read(query, {"tenant_id": tenant_id})
        if not results:
            return {"total": 0}
        return results[0]
