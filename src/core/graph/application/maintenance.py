import logging

from src.core.graph.application.communities.lifecycle import CommunityLifecycleManager
from src.core.graph.domain.ports.graph_client import GraphClientPort

logger = logging.getLogger(__name__)

class GraphMaintenanceService:
    """
    Service for periodic graph maintenance and integrity checks.
    """

    def __init__(self, graph_client: GraphClientPort):
        self.graph = graph_client
        self.lifecycle = CommunityLifecycleManager(graph_client)

    async def run_maintenance(self, tenant_id: str):
        """
        Runs all maintenance tasks for a tenant.
        """
        logger.info(f"Starting graph maintenance for tenant {tenant_id}")

        # 1. Rescue orphaned entities
        await self.lifecycle.cleanup_orphans(tenant_id)

        # 2. Check for broken community links
        await self.check_broken_links(tenant_id)

        # 3. Detect stalled summarization jobs
        await self.detect_stalled_jobs(tenant_id)

        logger.info(f"Maintenance complete for tenant {tenant_id}")

    async def check_broken_links(self, tenant_id: str):
        """
        Finds and fixes broken BELONGS_TO or PARENT_OF links.
        """
        # Find BELONGS_TO to non-existent Community
        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})-[r:BELONGS_TO]->(c)
        WHERE NOT (c:Community)
        DELETE r
        RETURN count(r) as count
        """
        result = await self.graph.execute_write(query, {"tenant_id": tenant_id})
        count = result[0]["count"] if result else 0
        if count > 0:
            logger.warning(f"Removed {count} broken BELONGS_TO links for tenant {tenant_id}")

    async def detect_stalled_jobs(self, tenant_id: str):
        """
        Resets communities stuck in 'processing' status for too long.
        """
        # Status 'processing' and updated more than 1 hour ago
        query = """
        MATCH (c:Community {tenant_id: $tenant_id})
        WHERE c.status = 'processing'
          AND datetime(c.updated_at) < datetime() - duration('PT1H')
        SET c.status = 'failed', c.error = 'Stalled job timeout'
        RETURN count(c) as count
        """
        result = await self.graph.execute_write(query, {"tenant_id": tenant_id})
        count = result[0]["count"] if result else 0
        if count > 0:
            logger.warning(f"Reset {count} stalled community summarization jobs for tenant {tenant_id}")
