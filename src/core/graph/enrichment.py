import logging
import asyncio
from typing import List, Optional
from src.core.graph.neo4j_client import neo4j_client
from src.core.graph.schema import RelationshipType, NodeLabel

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

    async def create_similarity_edges(self, chunk_id: str, embedding: List[float], tenant_id: str, threshold: float = 0.7, limit: int = 5):
        """
        Find similar chunks and create SIMILAR_TO edges.
        """
        if not self.vector_store:
            # Try to lazy load or fail
            try:
                from src.core.vector_store.milvus import get_milvus_client
                self.vector_store = get_milvus_client()
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
        queries = []
        for res in results:
            other_id = res.get("id")
            score = res.get("score", 0)
            
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
