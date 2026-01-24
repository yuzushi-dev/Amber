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
    try:
        logger.info("Initializing Milvus...")
        store = MilvusVectorStore(MilvusConfig())
        await store.connect()
        logger.info("Milvus initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Milvus: {e}")
        # We don't exit here, might be temporary, but good to log

async def init_neo4j():
    """Initialize Neo4j constraints."""
    try:
        logger.info("Initializing Neo4j...")
        await setup_constraints()
        logger.info("Neo4j initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Neo4j: {e}")

async def main():
    logger.info("Starting resource initialization...")
    await init_milvus()
    await init_neo4j()
    logger.info("Resource initialization finished.")

if __name__ == "__main__":
    asyncio.run(main())
