import logging

from src.core.retrieval.application.embeddings_service import EmbeddingService
from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService
from src.core.retrieval.domain.ports.vector_store_port import VectorStorePort

logger = logging.getLogger(__name__)


class CommunityEmbeddingService:
    """
    Handles embedding and storage of community summaries in the vector store.
    """

    FIELD_COMMUNITY_ID = "community_id"
    FIELD_TENANT_ID = "tenant_id"
    FIELD_LEVEL = "level"
    FIELD_TITLE = "title"
    FIELD_SUMMARY = "summary"
    FIELD_VECTOR = "vector"

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStorePort,
        sparse_embedding_service: SparseEmbeddingService | None = None,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.sparse_embedding_service = sparse_embedding_service

    # NOTE: embed_and_store_community and search_communities were removed.
    # The community pipeline (process_communities task) uses an inlined _embed_only
    # loop that writes payloads directly via vector_store.upsert_chunks, making
    # embed_and_store_community unreachable in production.
    # search_communities had no callers anywhere in the codebase.
    # This class is kept as a named container for embedding_service /
    # sparse_embedding_service so that tasks.py can initialise both services
    # under a single object and reference them by attribute.
