import asyncio
import logging

from src.core.graph.neo4j_client import neo4j_client
from src.core.graph.schema import NodeLabel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def setup_constraints():
    """Apply Neo4j constraints and indexes."""
    logger.info("Setting up Neo4j constraints and indexes...")

    constraints = [
        # Document constraints
        f"CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:{NodeLabel.Document.value}) REQUIRE d.id IS UNIQUE",

        # Chunk constraints
        f"CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:{NodeLabel.Chunk.value}) REQUIRE c.id IS UNIQUE",

        # Entity constraints (Unique per Name + Tenant)
        # Note: Neo4j partial uniqueness (composite keys) or just enforce in application logic + index
        # We'll use a composite constraint for strict enforcement if Enterprise,
        # but for Community edition we often rely on application or single-property constraint.
        # Let's assume standard uniqueness on ID first, BUT for entities we really want name+tenant uniqueness.
        # We'll create a composite index for lookup performance.
        f"CREATE INDEX entity_lookup IF NOT EXISTS FOR (e:{NodeLabel.Entity.value}) ON (e.name, e.tenant_id)",

        # Community constraints
        f"CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (c:{NodeLabel.Community.value}) REQUIRE c.id IS UNIQUE",
    ]

    # Vector Index creation (Neo4j 5.x+)
    # We need to drop if exists to change dims/similarity, but for setup we'll TRY connect.
    # Note: Vector indexes are created via specific procedures or DDL in newer versions.
    # We will skip vector index creation in this initial setup script to avoid version-specific syntax errors
    # until we confirm the exact Neo4j version capabilities, but we will add standard indexes.

    indexes = [
         f"CREATE INDEX document_tenant IF NOT EXISTS FOR (d:{NodeLabel.Document.value}) ON (d.tenant_id)",
         f"CREATE INDEX chunk_document IF NOT EXISTS FOR (c:{NodeLabel.Chunk.value}) ON (c.document_id)",
    ]

    try:
        await neo4j_client.connect()

        for constraint in constraints:
            logger.info(f"Applying constraint: {constraint}")
            await neo4j_client.execute_write(constraint)

        for index in indexes:
             logger.info(f"Applying index: {index}")
             await neo4j_client.execute_write(index)

        logger.info("Neo4j schema setup complete.")

    except Exception as e:
        logger.error(f"Failed to setup Neo4j schema: {e}")
        raise
    finally:
        await neo4j_client.close()

if __name__ == "__main__":
    asyncio.run(setup_constraints())
