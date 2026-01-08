import logging
from typing import Any, List, Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, status, Request
# from src.api.dependencies.auth import get_current_user_tenant_id # Removed invalid import
from src.core.graph.neo4j_client import neo4j_client
from src.core.vector_store.milvus import MilvusVectorStore, MilvusConfig
from src.api.config import settings
from src.core.services.embeddings import EmbeddingService

router = APIRouter(prefix="/graph/editor", tags=["Graph Editor"])
logger = logging.getLogger(__name__)

# Dependency to get tenant_id
def get_current_user_tenant_id(request: Request) -> str:
    """Resolve tenant ID from request context or default settings."""
    if hasattr(request.state, "tenant_id"):
        return str(request.state.tenant_id)
    return settings.tenant_id


# Request Models
class HealRequest(BaseModel):
    node_id: str

class MergeRequest(BaseModel):
    target_id: str
    source_ids: List[str]

class EdgeRequest(BaseModel):
    source: str
    target: str
    type: str = "RELATED_TO"
    description: str = ""

class HealingSuggestion(BaseModel):
    id: str
    name: str 
    type: str
    description: str = ""
    confidence: float
    reason: str

# --- Endpoints ---

@router.post("/heal", response_model=List[HealingSuggestion])
async def heal_node(
    request: HealRequest,
    tenant_id: str = Depends(get_current_user_tenant_id)
):
    """
    Suggest connections for a node based on Native Contextual Healing.
    Strategy:
    1. Find chunks linked to the node.
    2. Get vectors for those chunks from Milvus.
    3. Find similar chunks.
    4. Suggest entities from similar chunks.
    """
    try:
        # 1. Get Node Context
        context = await neo4j_client.get_node_context(request.node_id, tenant_id)
        if not context:
            raise HTTPException(status_code=404, detail="Node not found")
        
        chunk_ids = context.get("chunk_ids", [])
        
        # Initialize Vector Store
        # Note: In a real app, this should be a singleton dependency
        milvus_config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name=f"amber_{tenant_id}"
        )
        vector_store = MilvusVectorStore(milvus_config)
        
        query_vectors = []
        
        # 2. Get Vectors
        if chunk_ids:
            # We only use up to 3 chunks to avoid massive query fan-out
            target_chunks = chunk_ids[:3] 
            chunks_data = await vector_store.get_chunks(target_chunks)
            for ch in chunks_data:
                if "vector" in ch:
                    query_vectors.append(ch["vector"])
        else:
            # Fallback: Embed the node description/name if no chunks linked (Manual Node)
            text_to_embed = f"{context['name']}: {context['description']}"
            embedding_service = EmbeddingService(openai_api_key=settings.openai_api_key)
            # Create a single vector
            vec_result, _ = await embedding_service.embed_texts([text_to_embed])
            if vec_result:
                query_vectors.append(vec_result[0])

        if not query_vectors:
            return []

        # 3. Search Similar Chunks
        candidate_chunk_ids = set()
        
        # Parallel search? sequential for now
        for vec in query_vectors:
            results = await vector_store.search(
                query_vector=vec,
                tenant_id=tenant_id,
                limit=5,
                score_threshold=0.6 # Moderate similarity
            )
            for res in results:
                # Exclude own chunks
                if res.chunk_id not in chunk_ids:
                    candidate_chunk_ids.add(res.chunk_id)

        if not candidate_chunk_ids:
            return []

        # 4. Get Entities from Candidates
        entities = await neo4j_client.get_entities_from_chunks(list(candidate_chunk_ids), tenant_id)
        
        # Filter out the node itself and existing neighbors (optional, but good UX)
        # For now, just filter self
        suggestions = []
        for ent in entities:
             if ent['id'] == request.node_id:
                 continue
             
             # Calculate a simplistic confidence based on frequency in similar chunks
             # ent['frequency'] comes from the neo4j query
             score = min(0.5 + (ent['frequency'] * 0.1), 0.95)
             
             suggestions.append(HealingSuggestion(
                 id=ent['id'],
                 name=ent['name'],
                 type=ent['type'],
                 description=ent.get("description", "")[:100],
                 confidence=score,
                 reason=f"Appears in similar contexts ({ent['frequency']} chunks)"
             ))
             
        return suggestions

    except Exception as e:
        logger.error(f"Healing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nodes/merge")
async def merge_nodes(
    request: MergeRequest,
    tenant_id: str = Depends(get_current_user_tenant_id)
):
    """Merge source nodes into target node."""
    success = await neo4j_client.merge_nodes(request.target_id, request.source_ids, tenant_id)
    if not success:
        raise HTTPException(status_code=500, detail="Merge failed (check logs or APOC availability)")
    return {"status": "merged"}

@router.post("/edge")
async def create_edge(
    request: EdgeRequest,
    tenant_id: str = Depends(get_current_user_tenant_id)
):
    """Create a relationship."""
    query = """
    MATCH (s:Entity {name: $source, tenant_id: $tenant_id})
    MATCH (t:Entity {name: $target, tenant_id: $tenant_id})
    MERGE (s)-[r:RELATED_TO]->(t)
    SET r.type = $type, r.description = $description, r.weight = 1.0
    RETURN type(r)
    """
    await neo4j_client.execute_write(query, {
        "source": request.source,
        "target": request.target,
        "type": request.type,
        "description": request.description,
        "tenant_id": tenant_id
    })
    return {"status": "created"}

@router.delete("/edge")
async def delete_edge(
    request: EdgeRequest,
    tenant_id: str = Depends(get_current_user_tenant_id)
):
    """Delete a relationship."""
    query = """
    MATCH (s:Entity {name: $source, tenant_id: $tenant_id})-[r]->(t:Entity {name: $target, tenant_id: $tenant_id})
    DELETE r
    """
    await neo4j_client.execute_write(query, {
        "source": request.source,
        "target": request.target,
        "tenant_id": tenant_id
    })
    return {"status": "deleted"}

@router.delete("/node/{node_id}")
async def delete_node(
    node_id: str,
    tenant_id: str = Depends(get_current_user_tenant_id)
):
    """Delete a node and its relationships."""
    query = """
    MATCH (n:Entity {name: $node_id, tenant_id: $tenant_id})
    DETACH DELETE n
    """
    await neo4j_client.execute_write(query, {"node_id": node_id, "tenant_id": tenant_id})
    return {"status": "deleted"}

