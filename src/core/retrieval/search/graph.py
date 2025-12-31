import logging
from typing import Optional, Any
from src.core.models.candidate import Candidate
from src.core.graph.neo4j_client import Neo4jClient

from src.core.security.graph_traversal_guard import GraphTraversalGuard

logger = logging.getLogger(__name__)

class GraphSearcher:
    """
    Handles retrieval of chunks from Neo4j based on entity relationships.
    """
    
    def __init__(self, neo4j_client: Neo4jClient):
        self.neo4j = neo4j_client

    async def search_by_entities(
        self,
        entity_ids: list[str],
        tenant_id: str,
        limit: int = 10,
        allowed_doc_ids: Optional[list[str]] = None
    ) -> list[Candidate]:
        """
        Find chunks that mention the given entities.
        """
        if not entity_ids:
            return []
            
        acl_clause = ""
        params = {
            "entity_ids": entity_ids, 
            "tenant_id": tenant_id,
            "limit": limit
        }
        
        if allowed_doc_ids is not None:
            # Enforce ACLs
            acl_clause = f"AND {GraphTraversalGuard.get_acl_fragment('c', 'allowed_doc_ids')}"
            params["allowed_doc_ids"] = allowed_doc_ids

        query = f"""
        MATCH (e:Entity)-[:MENTIONS]-(c:Chunk)
        WHERE e.id IN $entity_ids AND e.tenant_id = $tenant_id 
        {acl_clause}
        RETURN DISTINCT c.id as chunk_id, c.content as content, c.document_id as document_id
        LIMIT $limit
        """
        
        try:
            results = await self.neo4j.execute_read(query, params)
            
            return [
                Candidate(
                    chunk_id=r["chunk_id"],
                    document_id=r["document_id"],
                    tenant_id=tenant_id,
                    content=r["content"],
                    score=1.0, # Initial score for graph hits
                    source="graph"
                )
                for r in results
            ]
            
        except Exception as e:
            logger.error(f"Graph search by entities failed: {e}")
            return []

    async def search_by_neighbors(
        self,
        chunk_ids: list[str],
        tenant_id: str,
        limit: int = 10,
        allowed_doc_ids: Optional[list[str]] = None
    ) -> list[Candidate]:
        """
        Find chunks that are neighbors of the given chunks in the graph
        (e.g., via shared entities or similarity edges).
        """
        if not chunk_ids:
            return []
            
        acl_clause = ""
        params = {
            "chunk_ids": chunk_ids,
            "tenant_id": tenant_id,
            "limit": limit
        }
        
        if allowed_doc_ids is not None:
             # Enforce ACLs on the neighbor chunk
            acl_clause = f"AND {GraphTraversalGuard.get_acl_fragment('neighbor', 'allowed_doc_ids')}"
            params["allowed_doc_ids"] = allowed_doc_ids

        query = f"""
        MATCH (start:Chunk)-[:MENTIONS]-(e:Entity)-[:MENTIONS]-(neighbor:Chunk)
        WHERE start.id IN $chunk_ids AND start.tenant_id = $tenant_id
          AND NOT neighbor.id IN $chunk_ids
          {acl_clause}
        RETURN DISTINCT neighbor.id as chunk_id, neighbor.content as content, neighbor.document_id as document_id
        LIMIT $limit
        """
        
        try:
            results = await self.neo4j.execute_read(query, params)
            
            return [
                Candidate(
                    chunk_id=r["chunk_id"],
                    document_id=r["document_id"],
                    tenant_id=tenant_id,
                    content=r["content"],
                    score=0.8, # Neighbor hits have slightly lower confidence
                    source="graph"
                )
                for r in results
            ]
        except Exception as e:
            logger.error(f"Graph search by neighbors failed: {e}")
            return []
