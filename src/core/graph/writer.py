import logging
import re
from typing import List, Dict, Any
from src.core.graph.neo4j_client import neo4j_client
from src.core.graph.schema import NodeLabel, RelationshipType
from src.core.prompts.entity_extraction import ExtractionResult

logger = logging.getLogger(__name__)


class GraphWriter:
    """
    Service to persist extracted knowledge graph data to Neo4j.
    Handles creation of Document, Chunk, Entity nodes and their relationships.
    """

    async def write_extraction_result(
        self, 
        document_id: str, 
        chunk_id: str, 
        tenant_id: str, 
        result: ExtractionResult
    ):
        """
        Persist extraction results for a single chunk.
        
        Args:
            document_id: ID of the parent document
            chunk_id: ID of the chunk
            tenant_id: Tenant context
            result: The extraction result object
        """
        if not result.entities and not result.relationships:
            logger.info(f"No graph data to write for chunk {chunk_id}")
            return

        # Prepare parameters
        # Normalize entity names slightly to reduce casing duplicates if LLM is inconsistent
        # But rely mostly on LLM prompt.
        
        entities_param = [e.model_dump() for e in result.entities]
        relationships_param = [r.model_dump() for r in result.relationships]

        # Cypher Query
        # We use strict MERGE to ensure idempotency.
        # Note: We rely on the constraint `ON (e:Entity) ASSERT (e.name, e.tenant_id) IS UNIQUE` 
        # (or similar) created in setup.
        
        query = f"""
        // 1. Ensure Context (Document & Chunk)
        MERGE (d:{NodeLabel.Document.value} {{id: $document_id}})
        ON CREATE SET d.tenant_id = $tenant_id
        
        MERGE (c:{NodeLabel.Chunk.value} {{id: $chunk_id}})
        ON CREATE SET c.document_id = $document_id, c.tenant_id = $tenant_id
        
        MERGE (d)-[:{RelationshipType.HAS_CHUNK.value}]->(c)
        """
        

        # 2. Merge Entities
        if entities_param:
            query += f"""
            WITH c
            UNWIND $entities as ent
            MERGE (e:{NodeLabel.Entity.value} {{name: ent.name, tenant_id: $tenant_id}})
            ON CREATE SET 
                e.type = ent.type, 
                e.description = ent.description,
                e.created_at = timestamp()
            // Link Chunk -> Entity
            MERGE (c)-[:{RelationshipType.MENTIONS.value}]->(e)
            """

        # Execute the base query (Doc, Chunk, Entities)
        params = {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "tenant_id": tenant_id,
            "entities": entities_param
        }

        try:
            await neo4j_client.execute_write(query, params)
            
            # 3. Native Relationship Merges (Batched by Type)
            if result.relationships:
                # Group relationships by sanitized type
                rels_by_type = {}
                for rel in result.relationships:
                    # Sanitize: UPPER_CASE only, replace special chars with _
                    safe_type = re.sub(r'[^A-Z0-9_]', '_', rel.type.upper())
                    if not safe_type: safe_type = "RELATED_TO"
                    
                    if safe_type not in rels_by_type:
                        rels_by_type[safe_type] = []
                    rels_by_type[safe_type].append(rel.model_dump())
                
                # Execute one batch per type
                for r_type, rel_batch in rels_by_type.items():
                    rel_query = f"""
                    UNWIND $batch as rel
                    MATCH (s:{NodeLabel.Entity.value} {{name: rel.source, tenant_id: $tenant_id}})
                    MATCH (t:{NodeLabel.Entity.value} {{name: rel.target, tenant_id: $tenant_id}})
                    MERGE (s)-[r:`{r_type}`]->(t)
                    ON CREATE SET 
                        r.description = rel.description, 
                        r.weight = rel.weight, 
                        r.tenant_id = $tenant_id,
                        r.created_at = timestamp()
                    ON MATCH SET
                        r.weight = rel.weight
                    """
                    await neo4j_client.execute_write(rel_query, {
                        "batch": rel_batch,
                        "tenant_id": tenant_id
                    })

            logger.info(
                f"Graph write complete for chunk {chunk_id}: "
                f"{len(entities_param)} entities, {len(result.relationships)} relationships"
            )

            # Trigger community staleness (Phase 4.3)
            try:
                from src.core.graph.communities.lifecycle import CommunityLifecycleManager
                lifecycle = CommunityLifecycleManager(neo4j_client)
                # Find the entity IDs from the graph (we only have names in params)
                # We can just use names if we update lifecycle to handle names and tenant_id
                # but it's safer to use the 'id' which we don't have here yet.
                # Actually, Neo4j MERGE uses name + tenant_id as unique key.
                # Let's update lifecycle to use names for efficiency.
                await lifecycle.mark_stale_by_entities_by_name([e["name"] for e in entities_param], tenant_id)
            except Exception as e:
                logger.warning(f"Failed to trigger community staleness: {e}")

        except Exception as e:
            logger.error(f"Failed to write graph data for chunk {chunk_id}: {e}")
            raise

graph_writer = GraphWriter()
