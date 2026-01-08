import math
import itertools
import logging
from src.core.graph.neo4j_client import neo4j_client
from src.core.graph.schema import NodeLabel, RelationshipType

# Import Vector Store Client (Assuming interface)
# Ideally dependency injection, but simple import for now
try:
    from src.core.vector_store.milvus import MilvusStore
    # Or get from factory/gloabl
except ImportError:
    MilvusStore = None

logger = logging.getLogger(__name__)

class GraphEnricher:
    """
    Enriches the Knowledge Graph with Computed Edges.
    - SIMILAR_TO (Chunk -> Chunk) based on vector similarity.
    - CO_OCCURS (Entity -> Entity) based on shared chunks (implicit or explicit).
    """

    def __init__(self, vector_store=None):
        self.vector_store = vector_store

    def _calculate_cosine_similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """Calculate cosine similarity between two embeddings."""
        if len(embedding1) != len(embedding2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        magnitude1 = math.sqrt(sum(a * a for a in embedding1))
        magnitude2 = math.sqrt(sum(a * a for a in embedding2))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    async def create_intra_document_similarities(self, chunks: list, threshold: float = 0.7, limit: int = 5):
        """
        Create SIMILAR_TO edges between chunks of the same document using in-memory comparison.
        This is robust for ensuring local connectivity.
        
        Args:
            chunks: List of Chunk objects (must have .id and .embedding)
            threshold: Similarity threshold (0.0 to 1.0)
            limit: Max connections per chunk (top k)
        """
        if len(chunks) < 2:
            return 0
            
        logger.info(f"Computing intra-document similarities for {len(chunks)} chunks...")
        
        # Prepare data: (id, embedding)
        # Filter out chunks without embeddings
        valid_chunks = []
        for c in chunks:
            # Handle if c is object or dict
            c_id = getattr(c, 'id', None) or c.get('id')
            emb = getattr(c, 'embedding', None) or c.get('embedding')
            if c_id and emb:
                valid_chunks.append((c_id, emb))
                
        if len(valid_chunks) < 2:
            return 0
            
        relationships_created = 0
        
        # O(N^2) comparison - okay for doc scope (usually < 1000 chunks)
        # For very large docs, this might need batching or optimization
        for i in range(len(valid_chunks)):
            id1, emb1 = valid_chunks[i]
            candidates = []
            
            for j in range(len(valid_chunks)):
                if i == j: 
                    continue
                    
                id2, emb2 = valid_chunks[j]
                
                sim = self._calculate_cosine_similarity(emb1, emb2)
                if sim >= threshold:
                    candidates.append((id2, sim))
            
            # Sort by score descending and take top K
            candidates.sort(key=lambda x: x[1], reverse=True)
            top_k = candidates[:limit]
            
            for rank, (id2, score) in enumerate(top_k):
                 query = f"""
                 MATCH (c1:{NodeLabel.Chunk.value} {{id: $id1}})
                 MATCH (c2:{NodeLabel.Chunk.value} {{id: $id2}})
                 MERGE (c1)-[r:{RelationshipType.SIMILAR_TO.value}]->(c2)
                 ON CREATE SET r.score = $score, r.rank = $rank, r.created_at = timestamp()
                 """
                 # We execute one by one for simplicity and safety, though batching is faster.
                 # Given async nature and connection pooling, this is acceptable for now.
                 await neo4j_client.execute_write(query, {
                     "id1": id1,
                     "id2": id2,
                     "score": score,
                     "rank": rank
                 })
                 relationships_created += 1
        
        logger.info(f"Created {relationships_created} intra-document similarity edges.")
        return relationships_created

    async def create_similarity_edges(self, chunk_id: str, embedding: list[float], tenant_id: str, threshold: float = 0.7, limit: int = 5):
        """
        Find similar chunks and create SIMILAR_TO edges.
        """
        if not self.vector_store:
            # Try to lazy load or fail
            try:
                from src.api.config import settings
                from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore
                
                config = MilvusConfig(
                    host=settings.db.milvus_host,
                    port=settings.db.milvus_port,
                    collection_name=f"amber_{tenant_id}" 
                )
                self.vector_store = MilvusVectorStore(config)
            except Exception as e:
                logger.error(f"Vector store not available: {e}")
                return

        # 1. Search Vector Store
        try:
            # Assume search returns list of matches: [{"id": "...", "score": 0.8}]
            # Implementation depends on Milvus wrapper signature
            results = await self.vector_store.search(
                collection_name="chunks",
                query_vector=embedding,
                limit=limit + 1, # +1 because it might find itself
                filters={"tenant_id": tenant_id}
            )
        except Exception as e:
            logger.error(f"Vector search failed for chunk {chunk_id}: {e}")
            return

        # 2. Filter and Create Edges
        for res in results:
            # Result is SearchResult dataclass, not dict
            other_id = res.chunk_id
            score = res.score if hasattr(res, 'score') else 0

            if other_id == chunk_id:
                continue

            if score < threshold:
                continue

            # Create Edge: (Chunk1)-[:SIMILAR_TO {score: ...}]->(Chunk2)
            # Undirected concept, but Neo4j is directed. We can create one way or both.
            # Usually strict A < B ID rule prevents double edges, or we just create one direction.
            # Let's create one direction for A->B where score is high.

            query = f"""
            MATCH (c1:{NodeLabel.Chunk.value} {{id: $id1}})
            MATCH (c2:{NodeLabel.Chunk.value} {{id: $id2}})
            MERGE (c1)-[r:{RelationshipType.SIMILAR_TO.value}]->(c2)
            ON CREATE SET r.score = $score, r.created_at = timestamp()
            """

            await neo4j_client.execute_write(query, {
                "id1": chunk_id,
                "id2": other_id,
                "score": score
            })

        logger.info(f"Created similarity edges for chunk {chunk_id}")

    async def compute_co_occurrence(self, tenant_id: str, min_weight: int = 2):
        """
        Compute Entity Co-occurrence based on shared chunks.
        (e1)-[:MENTIONS]-(c)-[:MENTIONS]-(e2)
        => (e1)-[:CO_OCCURS {weight: count(c)}]->(e2)

        This is a heavy analytical query using APOC or pure Cypher aggregation.
        """
        query = f"""
        MATCH (e1:{NodeLabel.Entity.value} {{tenant_id: $tenant_id}})<-[:{RelationshipType.MENTIONS.value}]-(c:{NodeLabel.Chunk.value})-[:{RelationshipType.MENTIONS.value}]->(e2:{NodeLabel.Entity.value} {{tenant_id: $tenant_id}})
        WHERE elementId(e1) < elementId(e2)
        WITH e1, e2, count(c) as weight
        WHERE weight >= $min_weight
        MERGE (e1)-[r:CO_OCCURS]-(e2)
        SET r.weight = weight
        """
        # Note: Dynamic rel type

        try:
             await neo4j_client.execute_write(query, {"tenant_id": tenant_id, "min_weight": min_weight})
             logger.info(f"Computed co-occurrence edges for tenant {tenant_id}")
        except Exception as e:
            logger.error(f"Failed to compute co-occurrence: {e}")

graph_enricher = GraphEnricher()
