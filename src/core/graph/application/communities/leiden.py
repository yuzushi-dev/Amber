import logging
from typing import Any
from uuid import uuid4

import igraph as ig
import leidenalg

from src.core.graph.domain.ports.graph_client import GraphClientPort
from src.shared.identifiers import generate_community_id

logger = logging.getLogger(__name__)


class CommunityDetector:
    """
    Implements Hierarchical Leiden Community Detection.
    Detects communities in the Knowledge Graph and persists them back to Neo4j.
    """

    def __init__(self, graph_client: GraphClientPort):
        self.graph = graph_client

    async def detect_communities(
        self, tenant_id: str, resolution: float = 1.0, max_levels: int = 2, seed: int = 42
    ) -> dict[str, Any]:
        """
        Main entry point for detection and persistence.

        Args:
            tenant_id: The tenant to detect communities for.
            resolution: Leiden resolution parameter (higher = smaller clusters).
            max_levels: Maximum hierarchy depth.

        Returns:
            Dict containing status and stats.
        """
        logger.info(f"Starting community detection for tenant {tenant_id}")

        generation_id = f"community-generation-{uuid4().hex}"

        # 1. Fetch L0 Graph (Entity-Entity)
        nodes, edges = await self._fetch_l0_graph(tenant_id)
        if not nodes:
            logger.info("No entities found, skipping community detection.")
            return {"status": "skipped", "reason": "no_entities"}

        logger.info(f"Fetched {len(nodes)} entities and {len(edges)} edges.")

        # 2. Run Hierarchical Leiden
        hierarchy = self._run_hierarchical_leiden(nodes, edges, resolution, max_levels, seed)

        # 3. Persist
        try:
            await self._persist_communities(tenant_id, hierarchy, generation_id)
            await self._validate_generation(tenant_id, generation_id, len(hierarchy))
        except Exception:
            await self.discard_generation(tenant_id, generation_id)
            raise

        count = len(hierarchy)
        logger.info(
            f"Detected and persisted {count} communities across levels for tenant {tenant_id}"
        )
        return {
            "status": "success",
            "community_count": count,
            "generation_id": generation_id,
        }

    async def _fetch_l0_graph(
        self, tenant_id: str
    ) -> tuple[list[str], list[tuple[str, str, float]]]:
        """
        Fetches all Entity nodes and their relationships.
        Returns:
            nodes: List of entity IDs (elementId or distinct ID property)
            edges: List of (source_id, target_id, weight)
        """
        # We use the 'name' property of Entity as the unique identifier (along with tenant_id)
        # Note: Entity nodes use (name, tenant_id) as their unique key, they don't have an 'id' property
        query = """
        MATCH (s:Entity)<-[:MENTIONS]-(source_chunk:Chunk)
        WHERE s.tenant_id = $tenant_id
          AND coalesce(source_chunk.is_published, true) = true
        WITH DISTINCT s
        OPTIONAL MATCH (s)-[r]->(t:Entity)
        WHERE t.tenant_id = $tenant_id
          AND NOT type(r) IN ['BELONGS_TO', 'PARENT_OF']
          AND coalesce(r.is_staging, false) = false
        RETURN s.name as source, t.name as target, type(r) as rel_type, properties(r) as props
        """
        results = await self.graph.execute_read(query, {"tenant_id": tenant_id})

        nodes = set()
        edges = []

        for record in results:
            src = record["source"]
            if src:
                nodes.add(src)

            tgt = record["target"]
            if tgt:
                nodes.add(tgt)
                # Simple count weight of 1.0 per edge, or use 'weight' property if exists
                weight = 1.0
                if record["props"] and "weight" in record["props"]:
                    try:
                        weight = float(record["props"]["weight"])
                    except (ValueError, TypeError):
                        weight = 1.0
                edges.append((src, tgt, weight))

        # If no relationships, we still have nodes. Leiden handles disconnected graphs.
        return sorted(nodes), edges

    def _run_hierarchical_leiden(
        self,
        nodes: list[str],
        edges: list[tuple[str, str, float]],
        resolution: float,
        max_levels: int,
        seed: int,
    ) -> list[dict[str, Any]]:
        """
        Runs Leiden recursively.
        Returns list of community dicts to persist.
        """
        # Map node string IDs to 0..N indices
        node_to_idx = {n: i for i, n in enumerate(nodes)}
        idx_to_node = {i: n for n, i in node_to_idx.items()}

        # Build igraph
        g = ig.Graph(len(nodes))
        ig_edges = []
        ig_weights = []

        for s, t, w in edges:
            if s in node_to_idx and t in node_to_idx:
                # igraph edges are (source_idx, target_idx)
                ig_edges.append((node_to_idx[s], node_to_idx[t]))
                ig_weights.append(w)

        g.add_edges(ig_edges)
        if ig_weights:
            g.es["weight"] = ig_weights

        results = []

        # --- Level 0 ---
        # Run Leiden
        # RBConfigurationVertexPartition is standard for Modularity-like optimization with resolution
        partition = leidenalg.find_partition(
            g,
            leidenalg.RBConfigurationVertexPartition,
            weights=ig_weights if ig_weights else None,
            resolution_parameter=resolution,
            seed=seed,
        )

        # Group members by community index
        l0_comms = {}  # comm_idx -> [node_ids]
        for node_idx, comm_idx in enumerate(partition.membership):
            if comm_idx not in l0_comms:
                l0_comms[comm_idx] = []
            l0_comms[comm_idx].append(idx_to_node[node_idx])

        # Assign UUIDs for L0 communities
        # Map comm_idx (int) -> comm_uuid (str)
        l0_idx_to_uuid = {}

        for c_idx, members in l0_comms.items():
            c_uuid = generate_community_id(level=0)
            l0_idx_to_uuid[c_idx] = c_uuid

            results.append(
                {
                    "id": c_uuid,
                    "level": 0,
                    "title": f"Community 0.{c_idx}",
                    "members": members,  # Entity IDs
                    "child_communities": [],  # L0 has no child communities
                }
            )

        if (
            max_levels <= 0
        ):  # max_levels=0 usually means just Entities? No, usually L0 is 1st level of communities.
            pass  # We return L0.

        if max_levels <= 1:
            return results

        # --- Level 1+ ---
        # Induce graph: Nodes are L0 communities.
        # leidenalg partition.aggregate_graph() creates a new graph where nodes represent the clusters.

        current_partition = partition
        current_level_uuids = l0_idx_to_uuid  # int (cluster idx in current partition) -> uuid

        for level in range(1, max_levels):
            # Aggregate
            try:
                # cluster_graph returns a graph where nodes are the clusters of the partition
                induced_graph = current_partition.cluster_graph()
            except Exception as e:
                logger.warning(f"Failed to aggregate graph at level {level}: {e}")
                break

            # Run Leiden on induced graph
            # This partitions the CLUSTERS into SUPER-CLUSTERS
            next_partition = leidenalg.find_partition(
                induced_graph,
                leidenalg.RBConfigurationVertexPartition,
                weights=induced_graph.es["weight"]
                if "weight" in induced_graph.es.attribute_names()
                else None,
                resolution_parameter=resolution,
                seed=seed,
            )

            # Map new clusters to old clusters (uuids)
            # new_comm_idx (in next_partition) group of old_comm_indices (nodes in induced_graph)

            # next_partition.membership maps: node_idx (which is old_comm_idx) -> new_comm_idx

            level_comms = {}  # new_comm_idx -> [old_comm_uuids]

            for old_comm_idx, new_comm_idx in enumerate(next_partition.membership):
                if new_comm_idx not in level_comms:
                    level_comms[new_comm_idx] = []

                # Retrieve the UUID of the old community
                if old_comm_idx in current_level_uuids:
                    level_comms[new_comm_idx].append(current_level_uuids[old_comm_idx])

            # Check for convergence: if every cluster contains exactly 1 old cluster, we are just copying. Stop.
            # i.e. num new clusters == num old clusters
            if len(level_comms) == induced_graph.vcount():
                logger.info(f"Community structure converged at level {level}. Stopping.")
                break

            new_level_uuids = {}  # new_comm_idx -> new_uuid

            for c_idx, child_uuids in level_comms.items():
                c_uuid = generate_community_id(level=level)
                new_level_uuids[c_idx] = c_uuid

                results.append(
                    {
                        "id": c_uuid,
                        "level": level,
                        "title": f"Community {level}.{c_idx}",
                        "members": [],
                        "child_communities": child_uuids,  # List of CommunityIds from level-1
                    }
                )

            current_partition = next_partition
            current_level_uuids = new_level_uuids

        return results

    async def _cleanup_old_communities(self, tenant_id: str) -> None:
        """
        Removes all existing Community nodes and their relationships for a tenant.

        Called before each Leiden detection run so that stale communities from
        previous runs do not accumulate. Operates in batches to avoid Neo4j
        memory pressure on large graphs.
        """
        logger.info(f"Cleaning up old communities for tenant {tenant_id}")
        batch_size = 5000

        # 1. Delete BELONGS_TO edges (Entity -> Community)
        while True:
            result = await self.graph.execute_write(
                """
                MATCH (e:Entity)-[b:BELONGS_TO]->(c:Community {tenant_id: $tenant_id})
                WITH b LIMIT $batch_size
                DELETE b
                RETURN count(*) AS deleted
                """,
                {"tenant_id": tenant_id, "batch_size": batch_size},
            )
            deleted = result[0]["deleted"] if result else 0
            if deleted == 0:
                break
            logger.debug(f"Deleted {deleted} BELONGS_TO edges for tenant {tenant_id}")

        # 2. Delete PARENT_OF edges (Community -> Community)
        while True:
            result = await self.graph.execute_write(
                """
                MATCH (c:Community {tenant_id: $tenant_id})-[p:PARENT_OF]->()
                WITH p LIMIT $batch_size
                DELETE p
                RETURN count(*) AS deleted
                """,
                {"tenant_id": tenant_id, "batch_size": batch_size},
            )
            deleted = result[0]["deleted"] if result else 0
            if deleted == 0:
                break
            logger.debug(f"Deleted {deleted} PARENT_OF edges for tenant {tenant_id}")

        # 3. Delete Community nodes
        while True:
            result = await self.graph.execute_write(
                """
                MATCH (c:Community {tenant_id: $tenant_id})
                WITH c LIMIT $batch_size
                DETACH DELETE c
                RETURN count(*) AS deleted
                """,
                {"tenant_id": tenant_id, "batch_size": batch_size},
            )
            deleted = result[0]["deleted"] if result else 0
            if deleted == 0:
                break
            logger.debug(f"Deleted {deleted} Community nodes for tenant {tenant_id}")

        logger.info(f"Old community cleanup complete for tenant {tenant_id}")

    async def _persist_communities(
        self, tenant_id: str, communities: list[dict[str, Any]], generation_id: str
    ):
        """
        Writes community nodes and relationships to Neo4j.
        """
        if not communities:
            return

        # Prepare parameters
        # We need to ensure we don't pass massive lists if possible, but for MVP it's OK.

        query = """
        UNWIND $communities AS c
        MERGE (comm:Community {id: c.id, tenant_id: $tenant_id, generation_id: $generation_id})
        ON CREATE SET
            comm.level = c.level,
            comm.title = c.title,
            comm.created_at = datetime()
        SET comm.updated_at = datetime(),
            comm.active = false,
            comm.is_stale = true,
            comm.status = 'pending'

        WITH comm, c

        // Link Entities (Level 0)
        // Note: 'members' is list of Entity names (using name as unique identifier within tenant)
        FOREACH (member_name IN [m IN c.members WHERE m IS NOT NULL] |
            MERGE (e:Entity {name: member_name, tenant_id: $tenant_id})
            MERGE (e)-[:BELONGS_TO]->(comm)
        )

        // Link Child Communities (Level > 0)
        // Note: 'child_communities' is list of Community IDs (Level - 1)
        FOREACH (child_id IN c.child_communities |
            MERGE (child:Community {
                id: child_id,
                tenant_id: $tenant_id,
                generation_id: $generation_id
            })
            MERGE (comm)-[:PARENT_OF]->(child)
        )
        """

        # Simple batching to avoid query size limits if many communities
        batch_size = 100
        for i in range(0, len(communities), batch_size):
            batch = communities[i : i + batch_size]
            await self.graph.execute_write(
                query,
                {
                    "communities": batch,
                    "tenant_id": tenant_id,
                    "generation_id": generation_id,
                },
            )

    async def _validate_generation(
        self, tenant_id: str, generation_id: str, expected_count: int
    ) -> None:
        result = await self.graph.execute_read(
            """
            MATCH (c:Community)
            WHERE c.tenant_id = $tenant_id AND c.generation_id = $generation_id
            OPTIONAL MATCH (c)-[:PARENT_OF]->(child:Community)
            WITH count(DISTINCT c) AS community_count,
                 count(CASE WHEN child IS NOT NULL
                                  AND (child.tenant_id <> $tenant_id
                                       OR child.generation_id <> $generation_id)
                            THEN 1 END) AS invalid_links
            RETURN community_count, invalid_links
            """,
            {"tenant_id": tenant_id, "generation_id": generation_id},
        )
        row = result[0] if result else {}
        if row.get("community_count", 0) != expected_count or row.get("invalid_links", 0):
            raise RuntimeError("Community generation validation failed")

    async def activate_generation(self, tenant_id: str, generation_id: str) -> None:
        result = await self.graph.execute_write(
            """
            MATCH (new:Community)
            WHERE new.tenant_id = $tenant_id AND new.generation_id = $generation_id
            WITH collect(new) AS staged
            WHERE size(staged) > 0
            OPTIONAL MATCH (old:Community)
            WHERE old.tenant_id = $tenant_id
              AND (old.generation_id IS NULL OR old.generation_id <> $generation_id)
            WITH staged, collect(old) AS old_communities
            FOREACH (old IN old_communities | SET old.active = false)
            FOREACH (new IN staged | SET new.active = true)
            RETURN size(staged) AS activated
            """,
            {"tenant_id": tenant_id, "generation_id": generation_id},
        )
        if not result or result[0].get("activated", 0) == 0:
            raise RuntimeError(f"Community generation {generation_id} was not activated")

    async def discard_generation(self, tenant_id: str, generation_id: str) -> None:
        await self.graph.execute_write(
            """
            MATCH (c:Community)
            WHERE c.tenant_id = $tenant_id AND c.generation_id = $generation_id
            DETACH DELETE c
            """,
            {"tenant_id": tenant_id, "generation_id": generation_id},
        )

    async def assign_orphans_and_mark_stale(self, tenant_id: str) -> dict[str, Any]:
        """
        Incremental update: assign entities not yet belonging to any community to their
        nearest Level-0 community (by neighbor connectivity), then mark those communities
        stale so the summarizer re-processes only them.

        Called instead of full Leiden when communities already exist and a new doc was ingested.
        Entities with no connected community (fully isolated new entities) are left unassigned;
        they will be picked up by the next full Leiden run.
        """
        # Assign orphan entities to the Level-0 community most connected to their neighbors.
        assign_result = await self.graph.execute_write(
            """
            MATCH (e:Entity {tenant_id: $tid})
            WHERE NOT (e)-[:BELONGS_TO]->(:Community)
              AND EXISTS {
                MATCH (source_chunk:Chunk)-[:MENTIONS]->(e)
                WHERE coalesce(source_chunk.is_published, true) = true
              }
            OPTIONAL MATCH (e)-[r]-(neighbor:Entity {tenant_id: $tid})
            WHERE NOT type(r) IN ['BELONGS_TO', 'PARENT_OF']
              AND coalesce(r.is_staging, false) = false
              AND EXISTS {
                MATCH (neighbor_chunk:Chunk)-[:MENTIONS]->(neighbor)
                WHERE coalesce(neighbor_chunk.is_published, true) = true
              }
            OPTIONAL MATCH (neighbor)-[:BELONGS_TO]->(c:Community {tenant_id: $tid, level: 0})
            WITH e, c, count(neighbor) AS score
            WHERE c IS NOT NULL
            ORDER BY score DESC
            WITH e, collect(c)[0] AS best_community
            WHERE best_community IS NOT NULL
            MERGE (e)-[:BELONGS_TO]->(best_community)
            SET best_community.is_stale = true
            RETURN count(e) AS assigned
            """,
            {"tid": tenant_id},
        )
        assigned = assign_result[0]["assigned"] if assign_result else 0

        # Count truly isolated entities that couldn't be placed.
        orphan_result = await self.graph.execute_read(
            """
            MATCH (e:Entity {tenant_id: $tid})
            WHERE NOT (e)-[:BELONGS_TO]->(:Community)
              AND EXISTS {
                MATCH (source_chunk:Chunk)-[:MENTIONS]->(e)
                WHERE coalesce(source_chunk.is_published, true) = true
              }
            RETURN count(e) AS unassigned
            """,
            {"tid": tenant_id},
        )
        unassigned = orphan_result[0]["unassigned"] if orphan_result else 0

        logger.info(
            f"Incremental community update for tenant {tenant_id}: "
            f"assigned={assigned} unassigned_orphans={unassigned}"
        )
        return {"assigned": assigned, "unassigned": unassigned}
