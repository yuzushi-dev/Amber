import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, basic_auth

from src.shared.kernel.observability import trace_span
from src.shared.kernel.runtime import get_settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """
    Async client for Neo4j Graph Database.
    Handles connection pooling and transaction management.
    """

    _driver: AsyncDriver | None = None

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        """
        Initialize Neo4j client.

        Args:
            uri: Neo4j connection URI. If None, reads from composition root.
            user: Neo4j username. If None, reads from composition root.
            password: Neo4j password. If None, reads from composition root.
        """
        if uri is None or user is None or password is None:
            settings = get_settings()
            uri = uri or settings.db.neo4j_uri
            user = user or settings.db.neo4j_user
            password = password or settings.db.neo4j_password

        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None

    async def connect(self):
        """Establish connection to Neo4j."""
        if not self._driver:
            try:
                self._driver = AsyncGraphDatabase.driver(
                    self.uri, auth=basic_auth(self.user, self.password)
                )
                # Verify connection
                await self._driver.verify_connectivity()
                logger.info("Connected to Neo4j at %s", self.uri)
            except Exception as e:
                logger.error("Failed to connect to Neo4j: %s", str(e))
                raise

    async def close(self):
        """Close the Neo4j driver connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    async def get_driver(self) -> AsyncDriver:
        """Get or create the driver instance."""
        if not self._driver:
            await self.connect()
        return self._driver

    @trace_span("Neo4j.execute_read")
    async def execute_read(
        self, query: str, parameters: dict[str, Any] = None
    ) -> list[dict[str, Any]]:
        """
        Execute a read-only transaction.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Returns:
            List of records as dictionaries
        """
        driver = await self.get_driver()

        async with driver.session() as session:
            try:
                result = await session.execute_read(self._execute_tx, query, parameters)
                return result
            except Exception as e:
                logger.error("Read transaction failed: %s", str(e))
                raise

    @trace_span("Neo4j.execute_write")
    async def execute_write(
        self, query: str, parameters: dict[str, Any] = None
    ) -> list[dict[str, Any]]:
        """
        Execute a write transaction.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Returns:
            List of records as dictionaries (if any)
        """
        driver = await self.get_driver()

        async with driver.session() as session:
            try:
                result = await session.execute_write(self._execute_tx, query, parameters)
                return result
            except Exception as e:
                logger.error("Write transaction failed: %s", str(e))
                raise

    async def _execute_tx(
        self, tx, query: str, parameters: dict[str, Any] = None
    ) -> list[dict[str, Any]]:
        """Helper to run transaction and collect results."""
        if parameters is None:
            parameters = {}

        result = await tx.run(query, parameters)
        records = [record.data() async for record in result]
        return records

    async def merge_nodes(self, target_id: str, source_ids: list[str], tenant_id: str) -> bool:
        """
        Merge source nodes into target node.
        Moves relationships and appends descriptions.
        """
        # 1. Move incoming edges
        move_incoming = """
        MATCH (target:Entity {name: $target_id, tenant_id: $tenant_id})
        MATCH (source:Entity) WHERE source.name IN $source_ids AND source.tenant_id = $tenant_id
        MATCH (source)<-[r]-(start)
        WHERE start.name <> $target_id
        CALL apoc.refactor.to(r, target) YIELD input, output, error
        RETURN count(*)
        """

        # 2. Move outgoing edges
        move_outgoing = """
        MATCH (target:Entity {name: $target_id, tenant_id: $tenant_id})
        MATCH (source:Entity) WHERE source.name IN $source_ids AND source.tenant_id = $tenant_id
        MATCH (source)-[r]->(end)
        WHERE end.name <> $target_id
        CALL apoc.refactor.from(r, target) YIELD input, output, error
        RETURN count(*)
        """

        # 3. Append descriptions and alias names
        # We store previous names in 'aliases' property or just description
        merge_props = """
        MATCH (target:Entity {name: $target_id, tenant_id: $tenant_id})
        MATCH (source:Entity) WHERE source.name IN $source_ids AND source.tenant_id = $tenant_id
        WITH target, source
        ORDER BY source.name
        WITH target, collect(source.name) as aliases, collect(source.description) as descs
        SET target.aliases = coalesce(target.aliases, []) + aliases

        // Append unique descriptions
        WITH target, descs
        SET target.description = target.description + "\\n" +
            reduce(s = "", d IN [d IN descs WHERE d IS NOT NULL AND NOT target.description CONTAINS d] | s + "\\n" + d)
        """

        # 4. Delete sources
        delete_sources = """
        MATCH (source:Entity) WHERE source.name IN $source_ids AND source.tenant_id = $tenant_id
        DETACH DELETE source
        """

        try:
            # We assume APOC is available. If not, we need a manual Cypher reconstruction fallback.
            # Checking APOC availability could be done at startup.
            # For now, we wrap in try-except block.
            await self.execute_write(
                move_incoming,
                {"target_id": target_id, "source_ids": source_ids, "tenant_id": tenant_id},
            )
            await self.execute_write(
                move_outgoing,
                {"target_id": target_id, "source_ids": source_ids, "tenant_id": tenant_id},
            )
            await self.execute_write(
                merge_props,
                {"target_id": target_id, "source_ids": source_ids, "tenant_id": tenant_id},
            )
            await self.execute_write(
                delete_sources, {"source_ids": source_ids, "tenant_id": tenant_id}
            )
            return True
        except Exception as e:
            logger.error(f"Merge nodes failed (verify APOC is installed): {e}")
            # Fallback for manual edge copy could be implemented here
            return False

    async def find_orphan_nodes(self, tenant_id: str, limit: int = 100) -> list[str]:
        """Find nodes with no relationships."""
        query = """
        MATCH (n:Entity {tenant_id: $tenant_id})
        WHERE NOT (n)--()
        RETURN n.name as id
        LIMIT $limit
        """
        result = await self.execute_read(query, {"tenant_id": tenant_id, "limit": limit})
        return [r["id"] for r in result]

    async def get_node_context(self, node_id: str, tenant_id: str) -> dict[str, Any]:
        """
        Get context for healing: Linked chunks and their node text.
        """
        query = """
        MATCH (e:Entity {name: $node_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (chunk:Chunk)-[:MENTIONS]->(e)
        RETURN e.name as name, e.description as description, collect(chunk.id) as chunk_ids
        """
        result = await self.execute_read(query, {"node_id": node_id, "tenant_id": tenant_id})
        if not result or result[0]["name"] is None:
            # If exact match fails, try ID just in case (migration compatibility)
            # But strictly speaking we use name.
            return None
        return result[0]

    async def get_entities_from_chunks(
        self, chunk_ids: list[str], tenant_id: str
    ) -> list[dict[str, Any]]:
        """
        Find entities mentioned in specific chunks.
        Used to find candidates from 'similar' chunks during healing.
        """
        query = """
        MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)
        WHERE c.id IN $chunk_ids AND c.tenant_id = $tenant_id
        RETURN DISTINCT e.name as id, e.name as name, e.type as type, e.description as description, count(c) as frequency
        ORDER BY frequency DESC
        LIMIT 50
        """
        # Note: chunk_ids usually already scoped by tenant, but we add tenant_id for safety
        return await self.execute_read(query, {"chunk_ids": chunk_ids, "tenant_id": tenant_id})

    async def verify_connectivity(self) -> bool:
        """Check if connected to Neo4j."""
        try:
            driver = await self.get_driver()
            await driver.verify_connectivity()
            return True
        except Exception:
            return False

    async def delete_tenant_data(self, tenant_id: str) -> int:
        """
        Delete all data associated with a tenant.
        Used during destructive migration.
        """
        query = """
        MATCH (n {tenant_id: $tenant_id})
        DETACH DELETE n
        RETURN count(n) as deleted
        """
        try:
            result = await self.execute_write(query, {"tenant_id": tenant_id})
            return result[0]["deleted"] if result else 0
        except Exception as e:
            logger.error(f"Failed to delete tenant data for {tenant_id}: {e}")
            raise

    async def prune_orphans(
        self, valid_doc_ids: list[str], valid_chunk_ids: list[str]
    ) -> dict[str, int]:
        """
        Remove chunks and entities that are not valid.

        Args:
            valid_doc_ids: List of valid Document IDs from Postgres.
            valid_chunk_ids: List of valid Chunk IDs from Postgres.

        Returns:
            Dictionary with counts of deleted items.
        """
        # 1. Delete orphan Documents
        # If document ID is not in valid_doc_ids, delete it
        # UNWIND creates rows, we want to filter EXISTING nodes against the list
        # Passing huge lists to Cypher can be slow, but for maintenance it's acceptable usually.
        # However, for huge datasets, logic should be inverted (find orphans via exclusion).

        # Strategy:
        # We can't pass ALL valid IDs if millions.
        # But here we assume this usage is for maintenance/debugging or moderate scale.
        # If lists are huge, we should batch. For now, simplistic implementation as requested.

        counts = {"documents": 0, "chunks": 0, "entities": 0}

        try:
            # A. Prune Documents
            # Find all documents in Graph
            # Check if they are in valid_docs. If not, delete.
            # Doing this entirely in Cypher requires passing the full list of valid IDs.
            # "MATCH (d:Document) WHERE NOT d.id IN $valid_ids DETACH DELETE d"

            # Batching is safer. But for now:
            query_docs = """
            MATCH (d:Document)
            WHERE NOT d.id IN $valid_ids
            DETACH DELETE d
            RETURN count(d) as deleted
            """
            res_docs = await self.execute_write(query_docs, {"valid_ids": valid_doc_ids})
            counts["documents"] = res_docs[0]["deleted"] if res_docs else 0

            # B. Prune Chunks
            query_chunks = """
            MATCH (c:Chunk)
            WHERE NOT c.id IN $valid_ids
            DETACH DELETE c
            RETURN count(c) as deleted
            """
            res_chunks = await self.execute_write(query_chunks, {"valid_ids": valid_chunk_ids})
            counts["chunks"] = res_chunks[0]["deleted"] if res_chunks else 0

            # C. Prune Entities (Orphans)
            # STRATEGY CHANGE: Instead of just deleting completely isolated nodes (WHERE NOT (e)--()),
            # we now delete ANY entity that is not mentioned by a valid chunk.
            # This handles "island" clusters that are connected to each other but detached from the knowledge base.

            # Since we just deleted invalid chunks in step B, we can trust existing chunks.
            query_entities = """
            MATCH (e:Entity)
            WHERE NOT (:Chunk)-[:MENTIONS]->(e)
            DETACH DELETE e
            RETURN count(e) as deleted
            """
            res_entities = await self.execute_write(query_entities)
            counts["entities"] = res_entities[0]["deleted"] if res_entities else 0

            # D. Prune Stale Communities
            # Delete communities that are not reachable from any Entity.
            # This handles hierarchical communities (C <- C <- E) correctly.
            # Note: We use DETACH DELETE to remove PARENT_OF relationships.
            # We use *1.. to handle any depth of IN_COMMUNITY or PARENT_OF hierarchy
            # effectively checking if the community roots a subgraph containing at least one Entity.
            # Logic: If no Entity points to this community (directly or indirectly), it is empty.
            query_communities = """
            MATCH (c:Community)
            WHERE NOT EXISTS { (:Entity)-[:IN_COMMUNITY|HAS_MEMBER*1..]->(c) }
            DETACH DELETE c
            RETURN count(c) as deleted
            """
            # Note: We include HAS_MEMBER in the pattern just in case data model varies, though verification showed absent.

            res_comm = await self.execute_write(query_communities)
            counts["communities"] = res_comm[0]["deleted"] if res_comm else 0

            logger.info(f"Pruned orphans: {counts}")
            return counts

        except Exception as e:
            logger.error(f"Failed to prune orphans: {e}")
            raise

    async def get_top_nodes(self, tenant_id: str, limit: int = 15) -> list[dict[str, Any]]:
        """
        Get top connected nodes for the global graph background.
        """
        query = """
        MATCH (n:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (n)-[r]-()
        WITH n, count(r) as degree
        ORDER BY degree DESC
        LIMIT $limit
        RETURN n.name as id, n.name as label, n.type as type, n.community as community_id, degree
        """
        return await self.execute_read(query, {"tenant_id": tenant_id, "limit": limit})

    async def search_nodes(
        self, query_str: str, tenant_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Search for nodes by name or description.
        """
        query = """
        MATCH (n:Entity {tenant_id: $tenant_id})
        WHERE toLower(n.name) CONTAINS toLower($q)
           OR toLower(n.description) CONTAINS toLower($q)
        RETURN n.name as id, n.name as label, n.type as type, n.community as community_id
        LIMIT $limit
        """
        return await self.execute_read(
            query, {"tenant_id": tenant_id, "q": query_str, "limit": limit}
        )

    async def get_node_neighborhood(
        self, node_id: str, tenant_id: str, limit: int = 50
    ) -> dict[str, Any]:
        """
        Get neighborhood as graph data (nodes list, edges list).
        Wrapper for get_node_neighborhood_graph to match naming convention.
        """
        return await self.get_node_neighborhood_graph(node_id, tenant_id, limit)

    async def get_node_neighborhood_graph(
        self, node_id: str, tenant_id: str, limit: int = 50
    ) -> dict[str, Any]:
        """
        Get neighborhood as graph data (nodes list, edges list).
        """
        query = """
        MATCH (center:Entity {name: $node_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (center)-[r]-(neighbor:Entity)
        RETURN
            center.name as c_id, center.type as c_type, center.community as c_comm,
            type(r) as r_type, startNode(r).name as source, endNode(r).name as target,
            neighbor.name as n_id, neighbor.type as n_type, neighbor.community as n_comm
        LIMIT $limit
        """
        records = await self.execute_read(
            query, {"node_id": node_id, "tenant_id": tenant_id, "limit": limit}
        )

        nodes = {}  # Map to dedup
        edges = []

        for row in records:
            if not row["c_id"]:
                continue  # Should not happen if center exists

            # Add center
            if row["c_id"] not in nodes:
                nodes[row["c_id"]] = {
                    "id": row["c_id"],
                    "label": row["c_id"],
                    "type": row["c_type"],
                    "community_id": row["c_comm"],
                    "degree": 1,  # Estimate
                }

            # Add neighbor and edge
            if row["n_id"]:
                if row["n_id"] not in nodes:
                    nodes[row["n_id"]] = {
                        "id": row["n_id"],
                        "label": row["n_id"],
                        "type": row["n_type"],
                        "community_id": row["n_comm"],
                    }

                edges.append(
                    {
                        "source": row["source"],  # Neo4j directionality
                        "target": row["target"],
                        "type": row["r_type"],
                    }
                )

        return {"nodes": list(nodes.values()), "edges": edges}

    async def export_graph(self, tenant_id: str) -> AsyncIterator[dict]:
        """
        Export graph nodes and relationships for a tenant.

        Yields:
            Dict containing graph entity data.
        """
        driver = await self.get_driver()

        # 1. Nodes
        query_nodes = """
        MATCH (n:Entity {tenant_id: $tenant_id})
        RETURN {
            type: 'node',
            labels: labels(n),
            properties: properties(n),
            elementId: elementId(n)
        } as item
        """
        async with driver.session() as session:
            result = await session.run(query_nodes, {"tenant_id": tenant_id})
            async for record in result:
                yield record["item"]

        # 2. Relationships
        query_rels = """
        MATCH (a:Entity {tenant_id: $tenant_id})-[r]->(b:Entity {tenant_id: $tenant_id})
        RETURN {
            type: 'relationship',
            start: a.name,
            end: b.name,
            rel_type: type(r),
            properties: properties(r),
            tenant_id: $tenant_id
        } as item
        """
        async with driver.session() as session:
            result = await session.run(query_rels, {"tenant_id": tenant_id})
            async for record in result:
                yield record["item"]

    async def import_graph(self, graph_data: Iterator[dict], mode: str = "merge") -> dict:
        """
        Import graph data.
        """
        stats = {"nodes_created": 0, "relationships_created": 0}

        node_batch = []
        rel_batch = []
        batch_size = 500

        for item in graph_data:
            if item["type"] == "node":
                node_batch.append(item)
                if len(node_batch) >= batch_size:
                    await self._import_nodes_batch(node_batch)
                    stats["nodes_created"] += len(node_batch)
                    node_batch = []
            elif item["type"] == "relationship":
                rel_batch.append(item)
                if len(rel_batch) >= batch_size:
                    await self._import_rels_batch(rel_batch)
                    stats["relationships_created"] += len(rel_batch)
                    rel_batch = []

        if node_batch:
            await self._import_nodes_batch(node_batch)
            stats["nodes_created"] += len(node_batch)
        if rel_batch:
            await self._import_rels_batch(rel_batch)
            stats["relationships_created"] += len(rel_batch)

        logger.info(f"Graph import completed: {stats}")
        return stats

    async def _import_nodes_batch(self, batch: list[dict]):
        # Use simple MERGE for compatibility
        # Assumes Entity label for all restored nodes
        query = """
        UNWIND $batch as row
        MERGE (n:Entity {name: row.properties.name, tenant_id: row.properties.tenant_id})
        SET n += row.properties
        """
        await self.execute_write(query, {"batch": batch})

    async def _import_rels_batch(self, batch: list[dict]):
        # Requires APOC for dynamic relationship type
        query = """
        UNWIND $batch as row
        MATCH (a:Entity {name: row.start, tenant_id: row.tenant_id})
        MATCH (b:Entity {name: row.end, tenant_id: row.tenant_id})
        CALL apoc.merge.relationship(a, row.rel_type, {}, row.properties, b) YIELD rel
        RETURN count(rel)
        """
        try:
            await self.execute_write(query, {"batch": batch})
        except Exception as e:
            logger.warning(f"Failed to import relationship batch (APOC required?): {e}")
