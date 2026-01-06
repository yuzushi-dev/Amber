import logging
from typing import Any

from src.core.services.embeddings import EmbeddingService
from src.core.vector_store.milvus import MilvusConfig, _get_milvus

logger = logging.getLogger(__name__)

class CommunityEmbeddingService:
    """
    Handles embedding and storage of community summaries in Milvus.
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
        config: MilvusConfig | None = None
    ):
        self.embedding_service = embedding_service
        self.config = config or MilvusConfig(collection_name="community_embeddings")
        self._collection = None
        self._connected = False

    async def connect(self):
        """Connects to Milvus and ensures the communities collection exists."""
        if self._connected:
            return

        milvus = _get_milvus()
        try:
            milvus["connections"].connect(
                alias="default",
                host=self.config.host,
                port=self.config.port,
            )

            if not milvus["utility"].has_collection(self.config.collection_name):
                await self._create_collection(milvus)
            else:
                self._collection = milvus["Collection"](self.config.collection_name)
                self._collection.load()

            self._connected = True
        except Exception as e:
            logger.error(f"Failed to connect to Milvus for communities: {e}")
            raise

    async def _create_collection(self, milvus: dict):
        """Creates the community_embeddings collection."""
        fields = [
            milvus["FieldSchema"](
                name=self.FIELD_COMMUNITY_ID,
                dtype=milvus["DataType"].VARCHAR,
                is_primary=True,
                max_length=64,
            ),
            milvus["FieldSchema"](
                name=self.FIELD_TENANT_ID,
                dtype=milvus["DataType"].VARCHAR,
                max_length=64,
            ),
            milvus["FieldSchema"](
                name=self.FIELD_LEVEL,
                dtype=milvus["DataType"].INT64,
            ),
            milvus["FieldSchema"](
                name=self.FIELD_TITLE,
                dtype=milvus["DataType"].VARCHAR,
                max_length=256,
            ),
            milvus["FieldSchema"](
                name=self.FIELD_SUMMARY,
                dtype=milvus["DataType"].VARCHAR,
                max_length=65535,
            ),
            milvus["FieldSchema"](
                name=self.FIELD_VECTOR,
                dtype=milvus["DataType"].FLOAT_VECTOR,
                dim=self.config.dimensions,
            ),
        ]

        schema = milvus["CollectionSchema"](
            fields=fields,
            description="Community report embeddings for global search",
        )

        self._collection = milvus["Collection"](
            name=self.config.collection_name,
            schema=schema,
        )

        # Create HNSW index
        index_params = {
            "metric_type": self.config.metric_type,
            "index_type": self.config.index_type,
            "params": {"M": 16, "efConstruction": 256},
        }
        self._collection.create_index(
            field_name=self.FIELD_VECTOR,
            index_params=index_params,
        )
        self._collection.load()
        logger.info(f"Created collection {self.config.collection_name}")

    async def embed_and_store_community(self, community_data: dict[str, Any]):
        """
        Embeds a community summary and stores it in Milvus.

        Args:
            community_data: Dict with id, tenant_id, level, title, summary
        """
        await self.connect()

        text_to_embed = f"{community_data['title']}: {community_data['summary']}"
        embedding = await self.embedding_service.embed_single(text_to_embed)

        data = [
            {
                self.FIELD_COMMUNITY_ID: community_data["id"],
                self.FIELD_TENANT_ID: community_data["tenant_id"],
                self.FIELD_LEVEL: community_data["level"],
                self.FIELD_TITLE: community_data["title"],
                self.FIELD_SUMMARY: community_data["summary"],
                self.FIELD_VECTOR: embedding,
            }
        ]

        try:
            self._collection.upsert(data)
            self._collection.flush()
            logger.info(f"Stored embedding for community {community_data['id']}")
        except Exception as e:
            logger.error(f"Failed to store community embedding: {e}")
            raise

    async def search_communities(
        self,
        query_vector: list[float],
        tenant_id: str,
        level: int | None = None,
        limit: int = 5
    ) -> list[dict[str, Any]]:
        """
        Searches for communities semantically similar to the query.
        """
        await self.connect()

        filter_expr = f'{self.FIELD_TENANT_ID} == "{tenant_id}"'
        if level is not None:
            filter_expr += f' && {self.FIELD_LEVEL} == {level}'

        search_params = {"metric_type": self.config.metric_type, "params": {"ef": 64}}

        results = self._collection.search(
            data=[query_vector],
            anns_field=self.FIELD_VECTOR,
            param=search_params,
            limit=limit,
            expr=filter_expr,
            output_fields=[
                self.FIELD_COMMUNITY_ID,
                self.FIELD_TITLE,
                self.FIELD_SUMMARY,
                self.FIELD_LEVEL
            ]
        )

        output = []
        for hits in results:
            for hit in hits:
                output.append({
                    "id": hit.entity.get(self.FIELD_COMMUNITY_ID),
                    "title": hit.entity.get(self.FIELD_TITLE),
                    "summary": hit.entity.get(self.FIELD_SUMMARY),
                    "level": hit.entity.get(self.FIELD_LEVEL),
                    "score": hit.score
                })
        return output
