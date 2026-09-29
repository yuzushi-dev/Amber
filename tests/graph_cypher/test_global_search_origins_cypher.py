"""Runs GlobalSearchService's community-origin Cypher against a real Neo4j.

The unit tests only pin the query text; this checks what the guards actually
do on data: legacy (no is_published) vs published vs unpublished chunks,
inactive communities, tenant isolation, and primary-document selection.

Opt-in: set AMBER_TEST_NEO4J_URI (and optionally AMBER_TEST_NEO4J_USER /
AMBER_TEST_NEO4J_PASSWORD). Use a throwaway instance, e.g.
    docker run --rm -d -p 7688:7687 -e NEO4J_AUTH=neo4j/testpassword neo4j:5-community
    AMBER_TEST_NEO4J_URI=bolt://localhost:7688 AMBER_TEST_NEO4J_PASSWORD=testpassword \
        python3 -m pytest tests/graph_cypher
Every node written carries a per-run tenant id and is deleted afterwards.
"""

import os
import uuid

import pytest
import pytest_asyncio

from src.core.retrieval.application.search.global_search import GlobalSearchService

NEO4J_URI = os.environ.get("AMBER_TEST_NEO4J_URI")

pytestmark = pytest.mark.skipif(not NEO4J_URI, reason="AMBER_TEST_NEO4J_URI not set")


class _DriverReader:
    """Minimal execute_read adapter over the official async driver."""

    def __init__(self, driver):
        self._driver = driver

    async def execute_read(self, query, params):
        async with self._driver.session() as session:
            result = await session.run(query, params)
            return [record.data() async for record in result]


@pytest_asyncio.fixture
async def graph():
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(
        NEO4J_URI,
        auth=(
            os.environ.get("AMBER_TEST_NEO4J_USER", "neo4j"),
            os.environ.get("AMBER_TEST_NEO4J_PASSWORD", "testpassword"),
        ),
    )
    run = uuid.uuid4().hex[:8]
    tenant, other_tenant = f"t-{run}", f"other-{run}"

    async def write(query, **params):
        async with driver.session() as session:
            await (await session.run(query, params)).consume()

    async def cleanup():
        await write(
            "MATCH (n) WHERE n.test_run = $run DETACH DELETE n",
            run=run,
        )

    async def add(community, doc, chunks, *, community_tenant=None, active=True, rel="BELONGS_TO"):
        """chunks: list of is_published values (None = legacy, property absent)."""
        props = {"id": community, "tenant_id": community_tenant or tenant, "test_run": run}
        if active is not None:
            props["active"] = active
        await write(
            "MERGE (com:Community {id: $props.id, tenant_id: $props.tenant_id}) SET com += $props",
            props=props,
        )
        await write("MERGE (d:Document {id: $doc, test_run: $run})", doc=doc, run=run)
        for published in chunks:
            chunk_props = {"id": f"{doc}-{uuid.uuid4().hex[:6]}", "test_run": run}
            if published is not None:
                chunk_props["is_published"] = published
            await write(
                f"""
                MATCH (d:Document {{id: $doc, test_run: $run}})
                MATCH (com:Community {{id: $community, tenant_id: $community_tenant}})
                CREATE (d)-[:HAS_CHUNK]->(c:Chunk)-[:MENTIONS]->(e:Entity {{test_run: $run}})
                       -[:{rel}]->(com)
                SET c = $chunk_props
                """,
                doc=doc,
                run=run,
                community=community,
                community_tenant=community_tenant or tenant,
                chunk_props=chunk_props,
            )

    await cleanup()
    try:
        yield GlobalSearchService(None, None, None, neo4j_client=_DriverReader(driver)), add, tenant, other_tenant, run
    finally:
        await cleanup()
        await driver.close()


def _ids(run, *names):
    return [f"{name}-{run}" for name in names]


@pytest.mark.asyncio
async def test_legacy_and_published_chunks_resolve_unpublished_do_not(graph):
    service, add, tenant, _other, run = graph
    legacy, published, unpublished = _ids(run, "legacy", "published", "unpublished")
    await add(legacy, f"doc-legacy-{run}", [None])
    await add(published, f"doc-published-{run}", [True])
    await add(unpublished, f"doc-unpublished-{run}", [False, False])

    origins = await service._resolve_community_origins([legacy, published, unpublished], tenant)

    assert origins == {legacy: f"doc-legacy-{run}", published: f"doc-published-{run}"}


@pytest.mark.asyncio
async def test_inactive_community_is_excluded_even_with_published_chunks(graph):
    service, add, tenant, _other, run = graph
    inactive, missing_flag = _ids(run, "inactive", "legacy-active")
    await add(inactive, f"doc-a-{run}", [True], active=False)
    # Communities written before the active flag existed must still resolve.
    await add(missing_flag, f"doc-b-{run}", [True], active=None, rel="IN_COMMUNITY")

    origins = await service._resolve_community_origins([inactive, missing_flag], tenant)

    assert origins == {missing_flag: f"doc-b-{run}"}


@pytest.mark.asyncio
async def test_other_tenant_community_with_same_id_is_not_visible(graph):
    service, add, tenant, other_tenant, run = graph
    (shared_id,) = _ids(run, "shared")
    await add(shared_id, f"doc-other-{run}", [True], community_tenant=other_tenant)

    assert await service._resolve_community_origins([shared_id], tenant) == {}
    assert await service._resolve_community_origins([shared_id], other_tenant) == {
        shared_id: f"doc-other-{run}"
    }


@pytest.mark.asyncio
async def test_primary_document_ignores_mentions_from_unpublished_chunks(graph):
    service, add, tenant, _other, run = graph
    (community,) = _ids(run, "mixed")
    # doc-big dominates by raw mention count, but only through unpublished chunks.
    await add(community, f"doc-big-{run}", [False, False, False, False])
    await add(community, f"doc-small-{run}", [True])

    origins = await service._resolve_community_origins([community], tenant)

    assert origins == {community: f"doc-small-{run}"}


@pytest.mark.asyncio
async def test_published_and_unpublished_chunks_of_same_document_count_only_published(graph):
    service, add, tenant, _other, run = graph
    (community,) = _ids(run, "ranked")
    # doc-x: 1 published + 3 unpublished mentions; doc-y: 2 published mentions.
    await add(community, f"doc-x-{run}", [True, False, False, False])
    await add(community, f"doc-y-{run}", [True, None])

    origins = await service._resolve_community_origins([community], tenant)

    assert origins == {community: f"doc-y-{run}"}
