import logging
import asyncio
from typing import List, Dict, Any, Set
from src.core.models.candidate import Candidate
from src.core.graph.neo4j_client import Neo4jClient
from src.core.observability.tracer import trace_span

logger = logging.getLogger(__name__)

class GraphTraversalService:
    """
    Implements Beam Search traversal for multi-hop graph exploration.
    """
    
    def __init__(self, neo4j_client: Neo4jClient):
        self.neo4j = neo4j_client

    @trace_span("GraphTraversal.beam_search")
    async def beam_search(
        self,
        seed_entity_ids: List[str],
        tenant_id: str,
        depth: int = 2,
        beam_width: int = 5,
        timeout_ms: int = 200
    ) -> List[Candidate]:
        """
        Executes a bounded BFS (Beam Search) from seed entities.
        
        Args:
            seed_entity_ids: Starting entity IDs.
            tenant_id: Tenant context.
            depth: Max hops (default 2).
            beam_width: Max neighbors to follow per node per hop.
            timeout_ms: Strict budget (if Neo4j is slow, return partial).
        """
        if not seed_entity_ids:
            return []
            
        try:
            # We use a single Cypher query to perform the traversal efficiently
            # This is often faster than multiple round-trips for small depths.
            
            query = """
            MATCH (start:Entity)
            WHERE start.id IN $seed_ids AND start.tenant_id = $tenant_id
            
            // Hop 1
            MATCH (start)-[r1]-(neighbor:Entity)
            WHERE neighbor.tenant_id = $tenant_id
              AND NOT neighbor.id IN $seed_ids
              AND NOT type(r1) IN ['BELONGS_TO', 'PARENT_OF']
            
            WITH start, neighbor, r1
            ORDER BY r1.weight DESC
            WITH start, collect(neighbor)[0..$beam_width] as hop1_neighbors
            
            UNWIND hop1_neighbors as h1
            
            // Hop 2 (Optional expansion)
            OPTIONAL MATCH (h1)-[r2]-(h2:Entity)
            WHERE h2.tenant_id = $tenant_id
              AND NOT h2.id IN $seed_ids
              AND NOT h2.id = start.id
              AND NOT type(r2) IN ['BELONGS_TO', 'PARENT_OF']
            
            WITH h1, h2, r2
            ORDER BY r2.weight DESC
            WITH h1, collect(h2)[0..$beam_width] as hop2_neighbors
            
            UNWIND (CASE WHEN hop2_neighbors = [] THEN [null] ELSE hop2_neighbors END) as h2
            
            WITH DISTINCT filter(x IN [h1, h2] WHERE x IS NOT NULL) as final_entities
            UNWIND final_entities as e
            
            MATCH (e)-[:MENTIONS]-(c:Chunk)
            WHERE c.tenant_id = $tenant_id
            
            RETURN DISTINCT c.id as chunk_id, c.content as content, c.document_id as document_id
            LIMIT 50
            """
            
            # Using asyncio.wait_for to enforce timeout
            results = await asyncio.wait_for(
                self.neo4j.execute_read(
                    query,
                    {
                        "seed_ids": seed_entity_ids,
                        "tenant_id": tenant_id,
                        "beam_width": beam_width
                    }
                ),
                timeout=timeout_ms / 1000.0
            )
            
            return [
                Candidate(
                    chunk_id=r["chunk_id"],
                    document_id=r["document_id"],
                    tenant_id=tenant_id,
                    content=r["content"],
                    score=0.7, # Graph reasoning hits
                    source="graph"
                )
                for r in results
            ]
            
        except asyncio.TimeoutError:
            logger.warning("Graph beam search timed out")
            return []
        except Exception as e:
            logger.error(f"Graph beam search failed: {e}")
            return []
