import logging
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify():
    logger.info("Verifying Hybrid Search Dependencies...")

    # 1. Check Transformers/Torch
    try:
        # We need to mock settings if imports trigger it
        os.environ["TENANT_ID"] = "test"
        from src.core.services.sparse_embeddings import HAS_DEPS

        if HAS_DEPS:
            logger.info("✅ SparseEmbeddingService dependencies (torch/transformers) found.")
            # svc = SparseEmbeddingService() # Loading might be slow/download model, skip for now or try?
            # logger.info("✅ SparseEmbeddingService initialized.")
        else:
            logger.warning("❌ SparseEmbeddingService dependencies MISSING.")
    except Exception as e:
        logger.error(f"❌ SparseEmbeddingService check failed: {e}")

    # 2. Check Milvus Client
    try:
        from pymilvus import DataType
        if hasattr(DataType, "SPARSE_FLOAT_VECTOR"):
             logger.info("✅ PyMilvus Client supports SPARSE_FLOAT_VECTOR.")
        else:
             logger.warning("❌ PyMilvus Client DOES NOT support SPARSE_FLOAT_VECTOR. Upgrade pymilvus!")

        from pymilvus import AnnSearchRequest, RRFRanker  # noqa: F401
        logger.info("✅ PyMilvus Client supports AnnSearchRequest and RRFRanker.")
    except ImportError:
         logger.warning("❌ PyMilvus Client missing Hybrid Search classes (AnnSearchRequest/RRFRanker).")
    except Exception as e:
         logger.error(f"❌ Milvus Client check failed: {e}")

if __name__ == "__main__":
    verify()
