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
        
        # Try importing Hybrid Search components
        try:
            from pymilvus import AnnSearchRequest, RRFRanker
        except ImportError:
            AnnSearchRequest = None
            RRFRanker = None

        return {
            "Collection": Collection,
            "CollectionSchema": CollectionSchema,
            "DataType": DataType,
            "FieldSchema": FieldSchema,
            "MilvusClient": MilvusClient,
            "connections": connections,
            "utility": utility,
            "AnnSearchRequest": AnnSearchRequest,
            "RRFRanker": RRFRanker,
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
    FIELD_SPARSE_VECTOR = "sparse_vector"
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
        import asyncio

        def _sync_connect():
            """Synchronous connection and loading logic."""
            # Connect using the connections module
            alias = "default"
            milvus["connections"].connect(
                alias=alias,
                host=self.config.host,
                port=self.config.port,
                user=self.config.user if self.config.user else None,
                password=self.config.password if self.config.password else None,
            )

            # Check if collection exists
            if not milvus["utility"].has_collection(self.config.collection_name):
                return None  # Need to create collection
            else:
                collection = milvus["Collection"](self.config.collection_name)
                collection.load()
                return collection

        try:
            # Run blocking operations in thread pool
            self._collection = await asyncio.wait_for(
                asyncio.to_thread(_sync_connect),
                timeout=30.0  # 30 second timeout for connection
            )
            
            if self._collection is None:
                await self._create_collection(milvus)

            self._connected = True
            logger.info(f"Connected to Milvus at {self.config.host}:{self.config.port}")

        except asyncio.TimeoutError:
            logger.error("Milvus connection timed out after 30 seconds")
            raise RuntimeError("Milvus connection timed out")
        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            raise

    async def _create_collection(self, milvus: dict) -> None:
        """Create the collection with proper schema."""
        logger.info(f"Creating collection: {self.config.collection_name}")

        # Define schema
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
        
        # Add Sparse Vector field if supported (Milvus 2.4+)
        if hasattr(milvus["DataType"], "SPARSE_FLOAT_VECTOR"):
            fields.append(
                milvus["FieldSchema"](
                    name=self.FIELD_SPARSE_VECTOR,
                    dtype=milvus["DataType"].SPARSE_FLOAT_VECTOR,
                )
            )

        schema = milvus["CollectionSchema"](
            fields=fields,
            description="Document chunk embeddings for semantic search",
            enable_dynamic_field=True
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
        
        # Create index for sparse vector if supported
        if hasattr(milvus["DataType"], "SPARSE_FLOAT_VECTOR"):
            sparse_index_params = {
                "metric_type": "IP",
                "index_type": "SPARSE_INVERTED_INDEX",
                "params": {"drop_ratio_build": 0.2},
            }
            try:
                self._collection.create_index(
                    field_name=self.FIELD_SPARSE_VECTOR,
                    index_params=sparse_index_params,
                )
            except Exception as e:
                logger.warning(f"Failed to create sparse index used standard parameters: {e}")

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

        logger.info(f"Collection {self.config.collection_name} created with HNSW index and Dynamic Fields")

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
                - ... any other metadata keys (will be stored as dynamic fields)
                
        Returns:
            Number of chunks upserted
        """
        if not chunks:
            return 0

        await self.connect()

        # Prepare data for insertion
        # With enable_dynamic_field=True, we can pass extra keys in the dict.
        data = []
        for c in chunks:
            # Base required fields
            row = {
                self.FIELD_CHUNK_ID: c["chunk_id"],
                self.FIELD_DOCUMENT_ID: c["document_id"],
                self.FIELD_TENANT_ID: c["tenant_id"],
                self.FIELD_CONTENT: c.get("content", "")[:65530],
                self.FIELD_VECTOR: c["embedding"],
            }
            
            # Add sparse vector if present
            if self.FIELD_SPARSE_VECTOR in c and c[self.FIELD_SPARSE_VECTOR]:
                row[self.FIELD_SPARSE_VECTOR] = c[self.FIELD_SPARSE_VECTOR]

            # Merge extra metadata (everything in c that isn't a reserved field)
            reserved = {
                self.FIELD_CHUNK_ID, self.FIELD_DOCUMENT_ID, 
                self.FIELD_TENANT_ID, self.FIELD_CONTENT, self.FIELD_VECTOR,
                self.FIELD_SPARSE_VECTOR,
                "metadata" # avoid nesting if passed explicitly
            }
            for k, v in c.items():
                if k not in reserved:
                    row[k] = v
                    
            data.append(row)

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
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar chunks.
        
        Args:
            query_vector: Query embedding
            tenant_id: Tenant ID for isolation
            document_ids: Optional filter to specific documents
            limit: Maximum results to return
            score_threshold: Minimum similarity score
            filters: Optional dictionary of metadata filters (e.g. {"quality_score >": 0.5})
            
        Returns:
            List of SearchResult ordered by similarity
        """
        await self.connect()

        # Build filter expression
        filter_list = [f'{self.FIELD_TENANT_ID} == "{tenant_id}"']
        if document_ids:
            doc_filter = " || ".join(
                f'{self.FIELD_DOCUMENT_ID} == "{doc_id}"' for doc_id in document_ids
            )
            filter_list.append(f"({doc_filter})")
            
        # Add dynamic filters
        if filters:
            for key, val in filters.items():
                # Simple handling for now: 'key': value -> key == value
                # or 'key >': value -> key > value
                # We can assume strict logical expression or simple equality
                # Let's support simple equality and basic operators if key contains space
                if isinstance(val, str):
                    val_str = f'"{val}"'
                else:
                    val_str = str(val).lower() if isinstance(val, bool) else str(val)

                if " " in key: # e.g. "quality_score >"
                    field, op = key.split(" ", 1)
                    filter_list.append(f"{field} {op} {val_str}")
                else:
                    filter_list.append(f"{key} == {val_str}")

        filter_expr = " && ".join(filter_list)

        # Search parameters
        search_params = {
            "metric_type": self.config.metric_type,
            "params": {"ef": 128},  # HNSW search param
        }

        import asyncio
        
        def _sync_search():
            """Synchronous search call."""
            return self._collection.search(
                data=[query_vector],
                anns_field=self.FIELD_VECTOR,
                param=search_params,
                limit=limit,
                expr=filter_expr,
                output_fields=["*"], # Retrieve all dynamic fields
            )

        try:
            # Run blocking search in thread pool with timeout
            results = await asyncio.wait_for(
                asyncio.to_thread(_sync_search),
                timeout=30.0
            )

            # Convert to SearchResult objects
            search_results = []
            for hits in results:
                for hit in hits:
                    # Apply score threshold if specified
                    if score_threshold and hit.score < score_threshold:
                        continue

                    # Extract all fields into metadata
                    meta = {}
                    reserved = {self.FIELD_CHUNK_ID, self.FIELD_DOCUMENT_ID, self.FIELD_TENANT_ID, self.FIELD_VECTOR}
                    for k, v in hit.entity.items():
                        if k not in reserved:
                            meta[k] = v

                    search_results.append(
                        SearchResult(
                            chunk_id=hit.entity.get(self.FIELD_CHUNK_ID),
                            document_id=hit.entity.get(self.FIELD_DOCUMENT_ID),
                            tenant_id=hit.entity.get(self.FIELD_TENANT_ID),
                            score=hit.score,
                            metadata=meta,
                        )
                    )

            logger.debug(f"Found {len(search_results)} results for search query")
            return search_results

        except asyncio.TimeoutError:
            logger.error("Milvus search timed out after 30 seconds")
            return []
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

    async def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector: dict[int, float],
        tenant_id: str,
        document_ids: list[str] | None = None,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        rrf_k: int = 60,
    ) -> list[SearchResult]:
        """
        Perform Hybrid Search (Dense + Sparse) with Reciprocal Rank Fusion (RRF).
        Requires Milvus 2.4+.
        """
        await self.connect()
        milvus = _get_milvus()
        
        # Check if hybrid search components are available
        if not milvus.get("AnnSearchRequest") or not milvus.get("RRFRanker"):
             logger.warning("Hybrid search components not found (pymilvus too old?), falling back to Dense search")
             return await self.search(dense_vector, tenant_id, document_ids=document_ids, limit=limit, filters=filters)

        # Build filter
        filter_list = [f'{self.FIELD_TENANT_ID} == "{tenant_id}"']
        if document_ids:
            doc_filter = " || ".join(
                f'{self.FIELD_DOCUMENT_ID} == "{doc_id}"' for doc_id in document_ids
            )
            filter_list.append(f"({doc_filter})")
            
        if filters:
            for key, val in filters.items():
                if isinstance(val, str):
                    val_str = f'"{val}"'
                else:
                    val_str = str(val).lower() if isinstance(val, bool) else str(val)
                filter_list.append(f"{key} == {val_str}")
        filter_expr = " && ".join(filter_list)

        # 1. Define Search Requests
        # Dense
        dense_req = milvus["AnnSearchRequest"](
            data=[dense_vector],
            ann_field=self.FIELD_VECTOR,
            param={"metric_type": self.config.metric_type, "params": {"ef": 128}},
            limit=limit,
            expr=filter_expr
        )
        
        # Sparse
        # Check if sparse vector is valid and collection has the field
        has_sparse_field = next((f for f in self._collection.schema.fields if f.name == self.FIELD_SPARSE_VECTOR), None)
        
        if not sparse_vector or not has_sparse_field:
            return await self.search(dense_vector, tenant_id, limit=limit, filters=filters)

        sparse_req = milvus["AnnSearchRequest"](
            data=[sparse_vector],
            ann_field=self.FIELD_SPARSE_VECTOR,
            param={"metric_type": "IP", "params": {"drop_ratio_build": 0.2}}, # IP usually for Sparse
            limit=limit,
            expr=filter_expr
        )

        # 2. Define Reranker
        ranker = milvus["RRFRanker"](k=rrf_k)

        import asyncio

        def _sync_hybrid():
            # Use the collection's hybrid_search method
            results = self._collection.hybrid_search(
                reqs=[dense_req, sparse_req],
                rerank=ranker,
                limit=limit,
                output_fields=["*"]
            )
            return results

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(_sync_hybrid),
                timeout=30.0
            )
            
            # Map results
            search_results = []
            for hits in results:
                for hit in hits:
                     # Extract all fields into metadata
                     meta = {}
                     reserved = {
                         self.FIELD_CHUNK_ID, self.FIELD_DOCUMENT_ID, 
                         self.FIELD_TENANT_ID, self.FIELD_VECTOR, self.FIELD_SPARSE_VECTOR
                     }
                     for k, v in hit.entity.items():
                         if k not in reserved:
                             meta[k] = v
                     
                     search_results.append(
                         SearchResult(
                             chunk_id=hit.entity.get(self.FIELD_CHUNK_ID),
                             document_id=hit.entity.get(self.FIELD_DOCUMENT_ID),
                             tenant_id=hit.entity.get(self.FIELD_TENANT_ID),
                             score=hit.score,
                             metadata=meta,
                         )
                     )
            return search_results

        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            # Fallback
            return await self.search(dense_vector, tenant_id, limit=limit, filters=filters)
