import logging
import uuid
import igraph as ig
import leidenalg
from typing import List, Dict, Any, Tuple, Set, Optional

from src.core.graph.neo4j_client import Neo4jClient
from src.shared.identifiers import generate_community_id

logger = logging.getLogger(__name__)

class CommunityDetector:
    """
    Implements Hierarchical Leiden Community Detection.
    Detects communities in the Knowledge Graph and persists them back to Neo4j.
    """

    def __init__(self, neo4j_client: Neo4jClient):
        self.neo4j = neo4j_client

    async def detect_communities(self, tenant_id: str, resolution: float = 1.0, max_levels: int = 2) -> Dict[str, Any]:
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
        
        # 1. Fetch L0 Graph (Entity-Entity)
        nodes, edges = await self._fetch_l0_graph(tenant_id)
        if not nodes:
            logger.info("No entities found, skipping community detection.")
            return {"status": "skipped", "reason": "no_entities"}
        
        logger.info(f"Fetched {len(nodes)} entities and {len(edges)} edges.")

        # 2. Run Hierarchical Leiden
        hierarchy = self._run_hierarchical_leiden(nodes, edges, resolution, max_levels)
        
        # 3. Persist
        await self._persist_communities(tenant_id, hierarchy)
        
        count = len(hierarchy)
        logger.info(f"Detected and persisted {count} communities across levels for tenant {tenant_id}")
        return {"status": "success", "community_count": count}

    async def _fetch_l0_graph(self, tenant_id: str) -> Tuple[List[str], List[Tuple[str, str, float]]]:
        """
        Fetches all Entity nodes and their relationships.
        Returns:
            nodes: List of entity IDs (elementId or distinct ID property)
            edges: List of (source_id, target_id, weight)
        """
        # We use the 'id' property of Entity which is 'ent_...'
        query = """
        MATCH (s:Entity)
        WHERE s.tenant_id = $tenant_id
        OPTIONAL MATCH (s)-[r]->(t:Entity)
        WHERE t.tenant_id = $tenant_id 
          AND NOT type(r) IN ['BELONGS_TO', 'PARENT_OF']
        RETURN s.id as source, t.id as target, type(r) as rel_type, properties(r) as props
        """
        results = await self.neo4j.execute_read(query, {"tenant_id": tenant_id})
        
        nodes = set()
        edges = []
        
        for record in results:
            src = record["source"]
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
        return list(nodes), edges

    def _run_hierarchical_leiden(self, nodes: List[str], edges: List[Tuple[str, str, float]], resolution: float, max_levels: int) -> List[Dict[str, Any]]:
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
            g.es['weight'] = ig_weights
        
        results = []
        
        # --- Level 0 ---
        # Run Leiden
        # RBConfigurationVertexPartition is standard for Modularity-like optimization with resolution
        partition = leidenalg.find_partition(
            g, 
            leidenalg.RBConfigurationVertexPartition, 
            weights=ig_weights if ig_weights else None,
            resolution_parameter=resolution
        )
        
        # Group members by community index
        l0_comms = {} # comm_idx -> [node_ids]
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
            
            results.append({
                "id": c_uuid,
                "level": 0,
                "title": f"Community 0.{c_idx}",
                "members": members, # Entity IDs
                "child_communities": [] # L0 has no child communities
            })
            
        if max_levels <= 0: # max_levels=0 usually means just Entities? No, usually L0 is 1st level of communities. 
            pass # We return L0.

        if max_levels <= 1:
            return results
            
        # --- Level 1+ ---
        # Induce graph: Nodes are L0 communities. 
        # leidenalg partition.aggregate_graph() creates a new graph where nodes represent the clusters.
        
        current_graph = g
        current_partition = partition
        current_level_uuids = l0_idx_to_uuid # int (cluster idx in current partition) -> uuid
        
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
                weights=induced_graph.es['weight'] if 'weight' in induced_graph.es.attribute_names() else None,
                resolution_parameter=resolution
            )
            
            # Map new clusters to old clusters (uuids)
            # new_comm_idx (in next_partition) group of old_comm_indices (nodes in induced_graph)
            
            # next_partition.membership maps: node_idx (which is old_comm_idx) -> new_comm_idx
            
            level_comms = {} # new_comm_idx -> [old_comm_uuids]
            
            non_trivial_clusters = 0
            
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

            new_level_uuids = {} # new_comm_idx -> new_uuid

            for c_idx, child_uuids in level_comms.items():
                c_uuid = generate_community_id(level=level)
                new_level_uuids[c_idx] = c_uuid
                
                results.append({
                    "id": c_uuid,
                    "level": level,
                    "title": f"Community {level}.{c_idx}",
                    "members": [], 
                    "child_communities": child_uuids # List of CommunityIds from level-1
                })
            
            current_graph = induced_graph
            current_partition = next_partition
            current_level_uuids = new_level_uuids
            
        return results

    async def _persist_communities(self, tenant_id: str, communities: List[Dict[str, Any]]):
        """
        Writes community nodes and relationships to Neo4j.
        """
        if not communities:
            return

        # Prepare parameters
        # We need to ensure we don't pass massive lists if possible, but for MVP it's OK.
        
        query = """
        UNWIND $communities AS c
        MERGE (comm:Community {id: c.id})
        ON CREATE SET 
            comm.tenant_id = $tenant_id,
            comm.level = c.level,
            comm.title = c.title,
            comm.created_at = datetime()
        SET comm.updated_at = datetime()
        
        WITH comm, c
        
        // Link Entities (Level 0)
        // Note: 'members' is list of Entity IDs
        FOREACH (member_id IN c.members | 
            MERGE (e:Entity {id: member_id})
            MERGE (e)-[:BELONGS_TO]->(comm)
        )
        
        // Link Child Communities (Level > 0)
        // Note: 'child_communities' is list of Community IDs (Level - 1)
        FOREACH (child_id IN c.child_communities |
            MERGE (child:Community {id: child_id})
            MERGE (comm)-[:PARENT_OF]->(child)
        )
        """
        
        # Simple batching to avoid query size limits if many communities
        batch_size = 100
        for i in range(0, len(communities), batch_size):
            batch = communities[i:i+batch_size]
            await self.neo4j.execute_write(query, {"communities": batch, "tenant_id": tenant_id})

