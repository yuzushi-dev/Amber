import argparse
import asyncio
import logging

from src.core.graph.application.maintenance import GraphMaintenanceService
from src.amber_platform.composition_root import platform

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main(tenant_id: str):
    maintenance = GraphMaintenanceService(platform.neo4j_client)
    await maintenance.run_maintenance(tenant_id)
    await platform.neo4j_client.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Maintain Knowledge Graph integrity.")
    parser.add_argument("--tenant", required=True, help="Tenant ID to maintain")
    args = parser.parse_args()

    asyncio.run(main(args.tenant))
