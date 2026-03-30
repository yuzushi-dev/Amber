
import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.config import settings
from src.core.graph.infrastructure.neo4j_client import Neo4jClient

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def debug_orphans():
    print("\n" + "="*50)
    print("   DEBUG ORPHAN CHUNKS")
    print("="*50 + "\n")


    # Debug credentials
    print("\nNeo4j Config:")
    print(f" - URI: {settings.db.neo4j_uri}")
    print(f" - User: {settings.db.neo4j_user}")
    print(f" - Password: {'*' * len(settings.db.neo4j_password) if settings.db.neo4j_password else 'NONE/EMPTY'}")

    # 1. PostgreSQL Source of Truth
    db_url = settings.db.database_url
    if "postgres:5432" in db_url:
        db_url = db_url.replace("postgres:5432", "localhost:5433")

    engine = create_async_engine(db_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    valid_chunk_ids = set()
    async with async_session() as session:
        # Use raw SQL to avoid ORM import issues
        res_chunks = await session.execute(text("SELECT id FROM chunks"))
        valid_chunk_ids = set(res_chunks.scalars().all())

    print("Postgres Source of Truth:")
    print(f" - Valid Chunks in DB:    {len(valid_chunk_ids)}\n")

    # 2. Neo4j Check
    g_client = Neo4jClient(
        uri=settings.db.neo4j_uri.replace("neo4j:7687", "localhost:7687"),
        user=settings.db.neo4j_user,
        password=settings.db.neo4j_password
    )
    await g_client.connect()

    # Get all chunks from Neo4j
    neo_chunks_res = await g_client.execute_read("MATCH (c:Chunk) RETURN c.id as id", {})
    neo_chunk_ids = set([c['id'] for c in neo_chunks_res])

    print("Neo4j State:")
    print(f" - Total Chunks in Graph: {len(neo_chunk_ids)}")

    # Check for chunks in Graph but not in DB
    orphan_chunks = neo_chunk_ids - valid_chunk_ids
    print(f" - Orphan Chunks (in Graph, not in DB): {len(orphan_chunks)}")

    if orphan_chunks:
        print(f"   Sample orphans: {list(orphan_chunks)[:5]}")

    # Check for chunks not attached to any Document
    detached_chunks_res = await g_client.execute_read(
        "MATCH (c:Chunk) WHERE NOT (c)<-[:HAS_CHUNK]-(:Document) RETURN count(c) as count", {}
    )
    detached_count = detached_chunks_res[0]['count']
    print(f" - Detached Chunks (no parent Document): {detached_count}")

    # Check Entities mentioned ONLY by orphan chunks
    # (Entities exist, but valid chunks don't mention them)
    # If a chunk is orphan, it might be the only one mentioning an entity.

    # Logic: Find entities where ALL incoming mentions come from orphan chunks?
    # Hard to query directly efficiently without passing all orphan IDs.
    # Instead, let's query: Entities that are mentioned, but NOT by any VALID chunk.

    # Actually, simpler: count entities. The user says 103 entities exist.
    # If we have 0 docs, we should have 0 entities (ideally).
    entity_res = await g_client.execute_read("MATCH (e:Entity) RETURN count(e) as count", {})
    entity_count = entity_res[0]['count']
    print(f" - Total Entities in Graph: {entity_count}")

    if entity_count > 0 and len(valid_chunk_ids) == 0:
        print("   CRITICAL: Entities exist but no valid chunks exist in DB!")

    await g_client.close()
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(debug_orphans())
