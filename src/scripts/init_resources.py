"""
Script to initialize external resources (Neo4j, Milvus) on startup.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.core.graph.application.setup import setup_constraints
from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore, MilvusConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_milvus():
    """Initialize Milvus collection."""
    from src.amber_platform.composition_root import get_settings_lazy
    settings = get_settings_lazy()
    try:
        logger.info(f"Initializing Milvus at {settings.db.milvus_host}:{settings.db.milvus_port}...")
        config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            dimensions=settings.embedding_dimensions or 1536
        )
        store = MilvusVectorStore(config)
        await store.connect()
        logger.info("Milvus initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Milvus: {e}")

async def init_neo4j():
    """Initialize Neo4j constraints."""
    from src.amber_platform.composition_root import platform
    try:
        logger.info("Initializing Neo4j via Platform...")
        # Ensure platform is initialized (configures graph_client)
        await platform.initialize()
        await setup_constraints()
        logger.info("Neo4j initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Neo4j: {e}")

async def main():
    logger.info("Starting resource initialization...")
    # Order matters: initialize platform first to setup clients
    await init_neo4j()
    await init_milvus()
    logger.info("Resource initialization finished.")

if __name__ == "__main__":
    asyncio.run(main())
