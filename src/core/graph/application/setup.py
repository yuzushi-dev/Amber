import asyncio
import logging

from src.core.graph.domain.ports.graph_client import get_graph_client
from src.core.graph.domain.schema import NodeLabel

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
        # Entity deduplication index — Community Edition limitation documented here.
        #
        # Desired invariant: (name, tenant_id) is unique per :Entity node.
        #
        # Neo4j Community Edition does NOT support NODE KEY or composite uniqueness
        # constraints (those require Enterprise Edition).  Therefore a database-level
        # uniqueness constraint cannot be created here.
        #
        # Instead, uniqueness is enforced application-side:
        #   • All entity upserts use MERGE on (name, tenant_id) as the match key, so
        #     duplicate nodes are never intentionally created.
        #   • Deduplication logic in src/core/graph/application/deduplication.py
        #     handles any residual duplicates introduced by concurrent writes.
        #
        # This composite index supports fast MERGE lookup and query predicates on
        # (name, tenant_id) — the same fields used as the MERGE key.
        #
        # If this deployment is upgraded to Neo4j Enterprise Edition, replace this
        # index with a NODE KEY constraint to get DB-enforced uniqueness:
        #   CREATE CONSTRAINT entity_name_tenant_unique IF NOT EXISTS
        #   FOR (e:Entity) REQUIRE (e.name, e.tenant_id) IS NODE KEY
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
        graph_client = get_graph_client()
        await graph_client.connect()

        for constraint in constraints:
            logger.info(f"Applying constraint: {constraint}")
            await graph_client.execute_write(constraint)

        for index in indexes:
            logger.info(f"Applying index: {index}")
            await graph_client.execute_write(index)

        logger.info("Neo4j schema setup complete.")

    except Exception as e:
        logger.error(f"Failed to setup Neo4j schema: {e}")
        raise
    finally:
        if "graph_client" in locals() and graph_client:
            await graph_client.close()


if __name__ == "__main__":
    asyncio.run(setup_constraints())
