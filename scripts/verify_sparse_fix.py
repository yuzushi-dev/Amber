
import asyncio
import logging
import sys

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock dependencies
sys.path.append("/app")
from src.core.graph.application.communities.embeddings import CommunityEmbeddingService
from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService
from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore


# Mock Embedding Service (Dense)
class MockEmbeddingService:
    async def embed_single(self, text):
        return [0.1] * 1536  # Return dummy vector of correct dimension

async def verify_sparse_embedding():
    logger.info("Starting verification of Sparse Vector Fix...")

    # 1. Initialize Services
    logger.info("Initializing SparseEmbeddingService...")
    sparse_svc = SparseEmbeddingService()
    if not sparse_svc.prewarm():
        logger.error("Failed to prewarm SparseEmbeddingService")
        return

    logger.info("Initializing MilvusVectorStore...")
    # Use MilvusConfig with correct host
    from src.core.retrieval.infrastructure.vector_store.milvus import MilvusConfig
    config = MilvusConfig(
        host="milvus",
        port=19530,
        collection_name="community_embeddings",
        dimensions=1536
    )
    vector_store = MilvusVectorStore(config=config)

    # Initialize CommunityEmbeddingService with BOTH services
    logger.info("Initializing CommunityEmbeddingService...")
    comm_svc = CommunityEmbeddingService(
        embedding_service=MockEmbeddingService(),
        vector_store=vector_store,
        sparse_embedding_service=sparse_svc
    )

    # 2. Create Dummy Community Data
    community_data = {
        "id": "test_verification_id_123",
        "tenant_id": "default",
        "level": 0,
        "title": "Test Community for Sparse Vector",
        "summary": "This is a test summary to verify that sparse vectors are generated and stored correctly in Milvus without crashing."
    }

    # 3. Run Embed and Store
    logger.info("Attempting to embed and store community...")
    try:
        await comm_svc.embed_and_store_community(community_data)
        logger.info("✅ SUCCESS: Community embedded and stored with sparse vector!")
    except Exception as e:
        logger.error(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise

    # 4. Cleanup
    try:
        await vector_store.delete_chunks(["test_verification_id_123"], "default")
        logger.info("Cleanup successful.")
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify_sparse_embedding())
