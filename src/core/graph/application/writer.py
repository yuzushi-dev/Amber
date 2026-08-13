import logging
import re
from typing import Any

from src.core.generation.application.prompts.entity_extraction import ExtractionResult
from src.core.graph.domain.ports.graph_client import get_graph_client
from src.core.graph.domain.schema import NodeLabel, RelationshipType

logger = logging.getLogger(__name__)


class GraphWriter:
    """
    Service to persist extracted knowledge graph data to Neo4j.
    Handles creation of Document, Chunk, Entity nodes and their relationships.
    """

    @staticmethod
    def _sanitize_relationship_type(raw_type: str) -> str:
        safe_type = re.sub(r"[^A-Z0-9_]", "_", raw_type.upper())
        return safe_type or "RELATED_TO"

    def _build_base_query_and_params(
        self,
        *,
        document_id: str,
        chunk_id: str,
        tenant_id: str,
        filename: str | None,
        generation_id: str | None,
        entities_param: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]]:
        chunk_identity = (
            "{id: $chunk_id, document_id: $document_id, generation_id: $generation_id}"
            if generation_id is not None
            else "{id: $chunk_id}"
        )
        query = f"""
        // 1. Ensure Context (Document & Chunk)
        MERGE (d:{NodeLabel.Document.value} {{id: $document_id}})
        ON CREATE SET d.tenant_id = $tenant_id, d.filename = $filename
        ON MATCH SET d.filename = CASE WHEN d.filename IS NULL THEN $filename ELSE d.filename END

        MERGE (c:{NodeLabel.Chunk.value} {chunk_identity})
        ON CREATE SET c.tenant_id = $tenant_id, c.is_published = $generation_id IS NULL

        MERGE (d)-[:{RelationshipType.HAS_CHUNK.value}]->(c)
        """

        if entities_param:
            query += f"""
            WITH c
            UNWIND $entities as ent
            MERGE (e:{NodeLabel.Entity.value} {{name: ent.name, tenant_id: $tenant_id}})
            ON CREATE SET
                e.type = ent.type,
                e.description = ent.description,
                e.created_at = timestamp()
            MERGE (c)-[:{RelationshipType.MENTIONS.value}]->(e)
            """

        params = {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "tenant_id": tenant_id,
            "filename": filename,
            "generation_id": generation_id,
            "entities": entities_param,
        }
        return query, params

    def _build_relationship_queries(
        self,
        *,
        relationships: list[Any],
        tenant_id: str,
        document_id: str,
        generation_id: str | None,
    ) -> list[tuple[str, dict[str, Any]]]:
        rels_by_type: dict[str, list[dict[str, Any]]] = {}
        for rel in relationships:
            safe_type = self._sanitize_relationship_type(rel.type)
            rels_by_type.setdefault(safe_type, []).append(rel.model_dump())

        statements: list[tuple[str, dict[str, Any]]] = []
        for r_type, rel_batch in rels_by_type.items():
            rel_query = f"""
            UNWIND $batch as rel
            MATCH (s:{NodeLabel.Entity.value} {{name: rel.source, tenant_id: $tenant_id}})
            MATCH (t:{NodeLabel.Entity.value} {{name: rel.target, tenant_id: $tenant_id}})
            MERGE (s)-[r:`{r_type}` {"{document_id: $document_id, generation_id: $generation_id}" if generation_id is not None else ""}]->(t)
            ON CREATE SET
                r.description = rel.description,
                r.weight = rel.weight,
                r.tenant_id = $tenant_id,
                r.created_at = timestamp()
                {", r.is_staging = true" if generation_id is not None else ""}
            ON MATCH SET
                r.weight = rel.weight
            """
            statements.append(
                (
                    rel_query,
                    {
                        "batch": rel_batch,
                        "tenant_id": tenant_id,
                        "document_id": document_id,
                        "generation_id": generation_id,
                    },
                )
            )
        return statements

    async def write_extraction_result(
        self,
        document_id: str,
        chunk_id: str,
        tenant_id: str,
        result: ExtractionResult,
        filename: str = None,
        generation_id: str | None = None,
    ):
        """
        Persist extraction results for a single chunk.

        Args:
            document_id: ID of the parent document
            chunk_id: ID of the chunk
            tenant_id: Tenant context
            result: The extraction result object
        """
        # NOTE: we intentionally do NOT early-return when a chunk has no entities/
        # relationships. The base query also creates the structural backbone
        # (Document, Chunk, HAS_CHUNK); skipping it would leave entity-less chunks
        # orphaned from their Document in the graph (no HAS_CHUNK edge), which
        # breaks (:Document)-[:HAS_CHUNK]->(:Chunk) traversals and causes
        # Postgres↔Neo4j chunk drift on deletion. The entity/relationship parts
        # below are already conditional on there being entities/relationships.

        # Prepare parameters
        # Normalize entity names slightly to reduce casing duplicates if LLM is inconsistent
        # But rely mostly on LLM prompt.

        entities_param = [e.model_dump() for e in result.entities]
        base_query, base_params = self._build_base_query_and_params(
            document_id=document_id,
            chunk_id=chunk_id,
            tenant_id=tenant_id,
            filename=filename,
            generation_id=generation_id,
            entities_param=entities_param,
        )
        relationship_queries = self._build_relationship_queries(
            relationships=result.relationships,
            tenant_id=tenant_id,
            document_id=document_id,
            generation_id=generation_id,
        )
        graph_client = get_graph_client()

        try:
            statements: list[tuple[str, dict[str, Any] | None]] = [(base_query, base_params)]
            statements.extend(relationship_queries)

            if relationship_queries and hasattr(graph_client, "execute_write_batch"):
                await graph_client.execute_write_batch(statements)
            else:
                await graph_client.execute_write(base_query, base_params)
                for rel_query, rel_params in relationship_queries:
                    await graph_client.execute_write(rel_query, rel_params)

            logger.info(
                f"Graph write complete for chunk {chunk_id}: "
                f"{len(entities_param)} entities, {len(result.relationships)} relationships"
            )

            # Trigger community staleness (Phase 4.3)
            try:
                if generation_id is not None:
                    return
                from src.core.graph.application.communities.lifecycle import (
                    CommunityLifecycleManager,
                )

                lifecycle = CommunityLifecycleManager(graph_client)
                await lifecycle.mark_stale_by_entities_by_name(
                    [e["name"] for e in entities_param], tenant_id
                )
            except Exception as e:
                logger.warning(f"Failed to trigger community staleness: {e}")

        except Exception as e:
            logger.error(f"Failed to write graph data for chunk {chunk_id}: {e}")
            raise


graph_writer = GraphWriter()
