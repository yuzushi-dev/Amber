"""
Orphan Cleanup Script
=====================

This script identifies and removes orphaned data in Neo4j and Milvus 
by cross-referencing with the PostgreSQL source of truth.

Usage:
    PYTHONPATH=. python scripts/cleanup_orphans.py [--dry-run]
"""

import asyncio
import argparse
import logging
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

from src.api.config import settings
from src.core.graph.infrastructure.neo4j_client import Neo4jClient
from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore, MilvusConfig
# Removed mapped class imports to avoid validation issues
# from src.core.ingestion.domain.document import Document
# from src.core.ingestion.domain.chunk import Chunk

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def cleanup(dry_run=True):
    print("\n" + "="*50)
    print(f"   ORPHAN CLEANUP {'(DRY RUN)' if dry_run else ''}")
    print("="*50 + "\n")

    
    # Debug credentials
    # print(f"Neo4j URI: {settings.db.neo4j_uri}")

    # 1. PostgreSQL Source of Truth
    db_url = settings.db.database_url
    # Use host port if running locally outside docker (safety check)
    if "postgres:5432" in db_url:
        db_url = db_url.replace("postgres:5432", "localhost:5433")
    
    engine = create_async_engine(db_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        # Get all valid IDs using raw SQL to avoid ORM issues in script context
        res_docs = await session.execute(text("SELECT id FROM documents"))
        valid_doc_ids = set(res_docs.scalars().all())
        
        res_chunks = await session.execute(text("SELECT id FROM chunks"))
        valid_chunk_ids = set(res_chunks.scalars().all())
        
    print(f"Postgres Source of Truth:")
    print(f" - Valid Documents: {len(valid_doc_ids)}")
    print(f" - Valid Chunks:    {len(valid_chunk_ids)}\n")

    # 2. Neo4j Cleanup
    g_client = Neo4jClient(
        uri=settings.db.neo4j_uri.replace("neo4j:7687", "localhost:7687"),
        user=settings.db.neo4j_user,
        password=settings.db.neo4j_password
    )
    await g_client.connect()
    
    # A. Find orphaned Documents
    neo_docs = await g_client.execute_read("MATCH (d:Document) RETURN d.id as id", {})
    orphan_neo_docs = [d['id'] for d in neo_docs if d['id'] not in valid_doc_ids]
    
    print(f"Neo4j Audit - Documents:")
    print(f" - Found {len(orphan_neo_docs)} orphaned Document nodes.")
    
    if not dry_run and orphan_neo_docs:
        for doc_id in orphan_neo_docs:
            print(f"   Deleting Document {doc_id}...")
            await g_client.execute_write(
                "MATCH (d:Document {id: $id}) DETACH DELETE d", 
                {"id": doc_id}
            )

    # B. Find orphaned Chunks
    # Chunks define what entities are "mentioned". If chunks are zombies, entities stay alive.
    neo_chunks = await g_client.execute_read("MATCH (c:Chunk) RETURN c.id as id", {})
    neo_chunk_ids = set([c['id'] for c in neo_chunks])
    orphan_chunk_ids = neo_chunk_ids - valid_chunk_ids
    
    print(f"Neo4j Audit - Chunks:")
    print(f" - Total Chunks in Graph: {len(neo_chunk_ids)}")
    print(f" - Orphan Chunks:         {len(orphan_chunk_ids)}")
    
    if not dry_run and orphan_chunk_ids:
        print(f"   Deleting {len(orphan_chunk_ids)} orphaned chunks...")
        # Batch delete for efficiency
        batch_size = 100
        orphan_list = list(orphan_chunk_ids)
        for i in range(0, len(orphan_list), batch_size):
            batch = orphan_list[i:i+batch_size]
            await g_client.execute_write(
                "MATCH (c:Chunk) WHERE c.id IN $ids DETACH DELETE c",
                {"ids": batch}
            )
        print("   Chunks deleted.")

    # C. Find orphaned Entities (no mentions)
    # Now that we (potentially) deleted orphan chunks, we check for entities that have no remaining mentions
    orphaned_entities = await g_client.execute_read(
        "MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-(:Chunk) RETURN count(e) as c", {}
    )
    orphan_count = orphaned_entities[0].get('c', 0)
    print(f"Neo4j Audit - Entities:")
    print(f" - Found {orphan_count} orphaned Entity nodes (no mentions).")
    
    if not dry_run and orphan_count > 0:
        print(f"   Deleting {orphan_count} orphaned entities...")
        await g_client.execute_write(
            "MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-(:Chunk) DETACH DELETE e", {}
        )

    await g_client.close()

    # 3. Milvus Cleanup
    print("\nMilvus Audit:")
    from pymilvus import connections, utility
    try:
        connections.connect(host='localhost', port='19530')
        collections = utility.list_collections()
        for col_name in collections:
            # We only touch amber_* collections or document_chunks
            if col_name.startswith("amber_") or col_name == "document_chunks":
                print(f" - Found collection: {col_name}")
                # We could implement logic to delete empty collections here if needed
    except Exception as e:
        print(f"Milvus connection skipped or failed: {e}")
    finally:
         if connections.has_connection('default'):
            connections.disconnect('default')

    print("\n" + "="*50)
    print("   CLEANUP COMPLETE")
    print("="*50 + "\n")
    await engine.dispose()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', default=False)
    args = parser.parse_args()
    
    asyncio.run(cleanup(dry_run=args.dry_run))
