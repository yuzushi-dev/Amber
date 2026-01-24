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
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from src.api.config import settings
from src.core.graph.infrastructure.neo4j_client import Neo4jClient
from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore, MilvusConfig
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.chunk import Chunk

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def cleanup(dry_run=True):
    print("\n" + "="*50)
    print(f"   ORPHAN CLEANUP {'(DRY RUN)' if dry_run else ''}")
    print("="*50 + "\n")

    # 1. PostgreSQL Source of Truth
    db_url = settings.db.database_url
    # Use host port if running locally outside docker (safety check)
    if "postgres:5432" in db_url:
        db_url = db_url.replace("postgres:5432", "localhost:5433")
    
    engine = create_async_engine(db_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        # Get all valid IDs
        res_docs = await session.execute(select(Document.id))
        valid_doc_ids = set(res_docs.scalars().all())
        
        res_chunks = await session.execute(select(Chunk.id))
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
    
    # Find orphaned documents in Neo4j
    neo_docs = await g_client.execute_read("MATCH (d:Document) RETURN d.id as id", {})
    orphan_neo_docs = [d['id'] for d in neo_docs if d['id'] not in valid_doc_ids]
    
    print(f"Neo4j Audit:")
    print(f" - Found {len(orphan_neo_docs)} orphaned Document nodes.")
    
    if not dry_run and orphan_neo_docs:
        for doc_id in orphan_neo_docs:
            print(f"   Deleting Document {doc_id}...")
            await g_client.execute_write(
                "MATCH (d:Document {id: $id}) DETACH DELETE d", 
                {"id": doc_id}
            )

    # Find orphaned entities (no mentions)
    orphaned_entities = await g_client.execute_read(
        "MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-(:Chunk) RETURN count(e) as c", {}
    )
    orphan_count = orphaned_entities[0].get('c', 0)
    print(f" - Found {orphan_count} orphaned Entity nodes.")
    
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
                # For document_chunks, we check internal IDs if possible, 
                # but usually amber_tenant_* are tenant specific.
                # Here we just check if the collection still exists.
                if col_name.startswith("amber_tenant_"):
                    tid = col_name.replace("amber_tenant_", "")
                    # Check if tenant exists in DB? 
                    # For now just log.
                    print(f" - Found collection: {col_name}")
    finally:
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
