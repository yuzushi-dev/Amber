import asyncio
import argparse
import logging
from src.core.graph.neo4j_client import neo4j_client
from src.core.graph.maintenance import GraphMaintenanceService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main(tenant_id: str):
    maintenance = GraphMaintenanceService(neo4j_client)
    await maintenance.run_maintenance(tenant_id)
    await neo4j_client.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Maintain Knowledge Graph integrity.")
    parser.add_argument("--tenant", required=True, help="Tenant ID to maintain")
    args = parser.parse_args()
    
    asyncio.run(main(args.tenant))
