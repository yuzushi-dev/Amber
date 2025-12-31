"""
Milvus Vector Store
===================

Vector storage and retrieval using Milvus.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import to avoid errors if pymilvus not installed
_milvus_connections = None


def _get_milvus():
    """Get pymilvus module with lazy loading."""
    try:
        from pymilvus import (
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            MilvusClient,
            connections,
            utility,
        )

        return {
            "Collection": Collection,
            "CollectionSchema": CollectionSchema,
            "DataType": DataType,
            "FieldSchema": FieldSchema,
            "MilvusClient": MilvusClient,
            "connections": connections,
            "utility": utility,
        }
    except ImportError:
        raise ImportError("pymilvus package is required. Install with: pip install pymilvus>=2.3.0")


@dataclass
class SearchResult:
    """A single search result."""

    chunk_id: str
    document_id: str
    tenant_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MilvusConfig:
    """Milvus connection configuration."""

    host: str = "localhost"
    port: int = 19530
    user: str = ""
    password: str = ""
    collection_name: str = "document_chunks"
    dimensions: int = 1536
    index_type: str = "HNSW"
    metric_type: str = "COSINE"


class MilvusVectorStore:
    """
    Milvus vector store for semantic search.
    
    Features:
    - Auto-creates collection with proper schema
    - HNSW indexing for fast search
    - Tenant isolation via filtering
    - Hybrid search support (vector + metadata filters)
    
    Usage:
        store = MilvusVectorStore(config)
        await store.connect()
        await store.upsert_chunks(chunks)
        results = await store.search(query_vector, tenant_id)
    """

    # Collection schema field names
    FIELD_CHUNK_ID = "chunk_id"
    FIELD_DOCUMENT_ID = "document_id"
    FIELD_TENANT_ID = "tenant_id"
    FIELD_VECTOR = "vector"
    FIELD_CONTENT = "content"
    FIELD_METADATA = "metadata"

    def __init__(self, config: MilvusConfig | None = None):
        self.config = config or MilvusConfig()
        self._client = None
        self._collection = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to Milvus and ensure collection exists."""
        if self._connected:
            return

        milvus = _get_milvus()

        try:
            # Connect using the connections module
            alias = "default"
            milvus["connections"].connect(
                alias=alias,
                host=self.config.host,
                port=self.config.port,
                user=self.config.user if self.config.user else None,
                password=self.config.password if self.config.password else None,
            )

            # Check if collection exists, create if not
            if not milvus["utility"].has_collection(self.config.collection_name):
                await self._create_collection(milvus)
            else:
                self._collection = milvus["Collection"](self.config.collection_name)
                self._collection.load()

            self._connected = True
            logger.info(f"Connected to Milvus at {self.config.host}:{self.config.port}")

        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            raise

    async def _create_collection(self, milvus: dict) -> None:
        """Create the collection with proper schema."""
        logger.info(f"Creating collection: {self.config.collection_name}")

        # Define schema
        fields = [
            milvus["FieldSchema"](
                name=self.FIELD_CHUNK_ID,
                dtype=milvus["DataType"].VARCHAR,
                is_primary=True,
                max_length=64,
            ),
            milvus["FieldSchema"](
                name=self.FIELD_DOCUMENT_ID,
                dtype=milvus["DataType"].VARCHAR,
                max_length=64,
            ),
            milvus["FieldSchema"](
                name=self.FIELD_TENANT_ID,
                dtype=milvus["DataType"].VARCHAR,
                max_length=64,
            ),
            milvus["FieldSchema"](
                name=self.FIELD_CONTENT,
                dtype=milvus["DataType"].VARCHAR,
                max_length=65535,  # Max for VARCHAR
            ),
            milvus["FieldSchema"](
                name=self.FIELD_VECTOR,
                dtype=milvus["DataType"].FLOAT_VECTOR,
                dim=self.config.dimensions,
            ),
        ]

        schema = milvus["CollectionSchema"](
            fields=fields,
            description="Document chunk embeddings for semantic search",
        )

        # Create collection
        self._collection = milvus["Collection"](
            name=self.config.collection_name,
            schema=schema,
        )

        # Create index for vector field
        index_params = {
            "metric_type": self.config.metric_type,
            "index_type": self.config.index_type,
            "params": {"M": 16, "efConstruction": 256},  # HNSW params
        }
        self._collection.create_index(
            field_name=self.FIELD_VECTOR,
            index_params=index_params,
        )

        # Create indexes for filter fields
        self._collection.create_index(
            field_name=self.FIELD_TENANT_ID,
            index_params={"index_type": "Trie"},
        )
        self._collection.create_index(
            field_name=self.FIELD_DOCUMENT_ID,
            index_params={"index_type": "Trie"},
        )

        # Load collection into memory
        self._collection.load()

        logger.info(f"Collection {self.config.collection_name} created with HNSW index")

    async def disconnect(self) -> None:
        """Disconnect from Milvus."""
        if self._connected:
            milvus = _get_milvus()
            milvus["connections"].disconnect("default")
            self._connected = False
            logger.info("Disconnected from Milvus")

    async def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
    ) -> int:
        """
        Insert or update chunks with their embeddings.
        
        Args:
            chunks: List of dicts with keys:
                - chunk_id: Unique chunk identifier
                - document_id: Parent document ID
                - tenant_id: Tenant for isolation
                - content: Chunk text content
                - embedding: Vector embedding
                
        Returns:
            Number of chunks upserted
        """
        if not chunks:
            return 0

        await self.connect()

        # Prepare data for insertion
        data = [
            {
                self.FIELD_CHUNK_ID: c["chunk_id"],
                self.FIELD_DOCUMENT_ID: c["document_id"],
                self.FIELD_TENANT_ID: c["tenant_id"],
                self.FIELD_CONTENT: c.get("content", "")[:65530],  # Truncate to max length
                self.FIELD_VECTOR: c["embedding"],
            }
            for c in chunks
        ]

        try:
            # Upsert (insert with replace semantics)
            self._collection.upsert(data)
            self._collection.flush()

            logger.info(f"Upserted {len(chunks)} chunks to Milvus")
            return len(chunks)

        except Exception as e:
            logger.error(f"Failed to upsert chunks: {e}")
            raise

    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        document_ids: list[str] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar chunks.
        
        Args:
            query_vector: Query embedding
            tenant_id: Tenant ID for isolation
            document_ids: Optional filter to specific documents
            limit: Maximum results to return
            score_threshold: Minimum similarity score
            
        Returns:
            List of SearchResult ordered by similarity
        """
        await self.connect()

        # Build filter expression
        filters = [f'{self.FIELD_TENANT_ID} == "{tenant_id}"']
        if document_ids:
            doc_filter = " || ".join(
                f'{self.FIELD_DOCUMENT_ID} == "{doc_id}"' for doc_id in document_ids
            )
            filters.append(f"({doc_filter})")

        filter_expr = " && ".join(filters)

        # Search parameters
        search_params = {
            "metric_type": self.config.metric_type,
            "params": {"ef": 128},  # HNSW search param
        }

        try:
            results = self._collection.search(
                data=[query_vector],
                anns_field=self.FIELD_VECTOR,
                param=search_params,
                limit=limit,
                expr=filter_expr,
                output_fields=[
                    self.FIELD_CHUNK_ID,
                    self.FIELD_DOCUMENT_ID,
                    self.FIELD_TENANT_ID,
                    self.FIELD_CONTENT,
                ],
            )

            # Convert to SearchResult objects
            search_results = []
            for hits in results:
                for hit in hits:
                    # Apply score threshold if specified
                    if score_threshold and hit.score < score_threshold:
                        continue

                    search_results.append(
                        SearchResult(
                            chunk_id=hit.entity.get(self.FIELD_CHUNK_ID),
                            document_id=hit.entity.get(self.FIELD_DOCUMENT_ID),
                            tenant_id=hit.entity.get(self.FIELD_TENANT_ID),
                            score=hit.score,
                            metadata={"content": hit.entity.get(self.FIELD_CONTENT, "")},
                        )
                    )

            logger.debug(f"Found {len(search_results)} results for search query")
            return search_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise

    async def get_chunks(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        """
        Retrieve chunks by ID.

        Args:
            chunk_ids: List of chunk IDs to retrieve

        Returns:
            List of chunk dicts (including content)
        """
        if not chunk_ids:
            return []

        await self.connect()

        try:
            # quote IDs for expression
            quoted_ids = [f'"{cid}"' for cid in chunk_ids]
            expr = f'{self.FIELD_CHUNK_ID} in [{", ".join(quoted_ids)}]'

            results = self._collection.query(
                expr=expr,
                output_fields=[
                    self.FIELD_CHUNK_ID,
                    self.FIELD_DOCUMENT_ID,
                    self.FIELD_TENANT_ID,
                    self.FIELD_CONTENT,
                ],
            )
            return results

        except Exception as e:
            logger.error(f"Failed to get chunks: {e}")
            return []

    async def delete_by_document(
        self,
        document_id: str,
        tenant_id: str,
    ) -> int:
        """Delete all chunks for a document."""
        await self.connect()

        expr = (
            f'{self.FIELD_DOCUMENT_ID} == "{document_id}" && '
            f'{self.FIELD_TENANT_ID} == "{tenant_id}"'
        )

        try:
            result = self._collection.delete(expr=expr)
            self._collection.flush()

            count = result.delete_count if hasattr(result, "delete_count") else 0
            logger.info(f"Deleted {count} chunks for document {document_id}")
            return count

        except Exception as e:
            logger.error(f"Failed to delete chunks: {e}")
            raise

    async def delete_by_tenant(self, tenant_id: str) -> int:
        """Delete all chunks for a tenant."""
        await self.connect()

        expr = f'{self.FIELD_TENANT_ID} == "{tenant_id}"'

        try:
            result = self._collection.delete(expr=expr)
            self._collection.flush()

            count = result.delete_count if hasattr(result, "delete_count") else 0
            logger.info(f"Deleted {count} chunks for tenant {tenant_id}")
            return count

        except Exception as e:
            logger.error(f"Failed to delete chunks: {e}")
            raise

    async def get_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        await self.connect()

        try:
            stats = self._collection.describe()
            return {
                "collection_name": self.config.collection_name,
                "num_entities": self._collection.num_entities,
                "schema": str(stats),
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}
