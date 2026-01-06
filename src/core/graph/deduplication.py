import logging
from difflib import SequenceMatcher

from src.core.graph.neo4j_client import neo4j_client
from src.core.graph.schema import NodeLabel, RelationshipType

logger = logging.getLogger(__name__)

class DeduplicationService:
    """
    Service to find and resolve duplicate entities in the Knowledge Graph.
    """

    async def find_candidates(self, tenant_id: str, threshold: float = 0.85) -> list[dict]:
        """
        Find candidate pairs for deduplication using string distance on names.

        Args:
            tenant_id: Tenant context
            threshold: Similarity threshold (0.0 - 1.0)

        Returns:
            List of candidate dictionaries
        """
        # Retrieve entities with potentially similar names (start with same letter/prefix)
        # to avoid N^2 in python.
        query = f"""
        MATCH (e:{NodeLabel.Entity.value} {{tenant_id: $tenant_id}})
        RETURN elementId(e) as id, e.name as name
        LIMIT 1000
        """

        try:
            results = await neo4j_client.execute_read(query, {"tenant_id": tenant_id})
        except Exception as e:
            logger.error(f"Failed to fetch entities for deduplication: {e}")
            return []

        candidates = []
        # Python-side comparison (O(N^2) naive, optimize later)
        # For < 1000 items it's fine.
        processed = set()

        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                e1 = results[i]
                e2 = results[j]

                # Check cache/processed
                pair_key = tuple(sorted((e1["id"], e2["id"])))
                if pair_key in processed:
                    continue

                processed.add(pair_key)

                sim = SequenceMatcher(None, e1["name"].lower(), e2["name"].lower()).ratio()

                if sim >= threshold:
                    candidates.append({
                        "entity1": {"id": e1["id"], "name": e1["name"]},
                        "entity2": {"id": e2["id"], "name": e2["name"]},
                        "similarity": sim
                    })

        return candidates

    async def resolve_entities(self, entity_id_keep: str, entity_id_merge: str, strategy: str = "soft_link"):
        """
        Resolve a pair of entities.

        Args:
            entity_id_keep: ID of the primary entity
            entity_id_merge: ID of the entity to merge/link
            strategy: 'soft_link' (default) or 'hard_merge'
        """
        if strategy == "soft_link":
            # Create a localized relationship indicating similarity
            query = f"""
            MATCH (e1), (e2)
            WHERE elementId(e1) = $id1 AND elementId(e2) = $id2
            MERGE (e1)-[r:{RelationshipType.POTENTIALLY_SAME_AS.value}]-(e2)
            SET r.similarity = $sim, r.created_at = timestamp()
            """
            # Note: Undirected relationship pattern (e1)-(e2) not supported in MERGE without direction
            # We'll creating directed one or handle direction.
            # Using: MERGE (e1)-[:REL]->(e2)

            query = f"""
            MATCH (e1), (e2)
            WHERE elementId(e1) = $id1 AND elementId(e2) = $id2
            MERGE (e1)-[r:{RelationshipType.POTENTIALLY_SAME_AS.value}]->(e2)
            ON CREATE SET r.strategy = 'soft_link', r.timestamp = timestamp()
            """

            await neo4j_client.execute_write(query, {"id1": entity_id_keep, "id2": entity_id_merge})
            logger.info(f"Soft linked entities {entity_id_keep} and {entity_id_merge}")

        elif strategy == "hard_merge":
            # Placeholder for hard merge complexity
            # Would require re-linking all relationships
            logger.warning("Hard Merge strategy not yet implemented safely.")
            # We could implement a simple logic here if required:
            # COPY RELS -> DELETE OLD
            pass

deduplication_service = DeduplicationService()
