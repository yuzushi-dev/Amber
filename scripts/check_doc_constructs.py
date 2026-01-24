#!/usr/bin/env python3
"""
Check Document Constructs
=========================

Verifies all constructs for a given document:
- Document metadata (PostgreSQL)
- Chunks (PostgreSQL + Milvus)
- Entities (Neo4j)
- Relationships (Neo4j)
- Communities (Neo4j)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.config import settings
from src.core.database.session import async_session_maker
from src.core.models.document import Document
from src.core.models.chunk import Chunk
from src.amber_platform.composition_root import platform
Neo4jClient = type(platform.neo4j_client)
neo4j_client = platform.neo4j_client

from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore
from sqlalchemy import select, func


async def check_document(filename_pattern: str = "Carbonio"):
    """Check all constructs for a document matching the filename pattern."""
    
    print(f"🔍 Searching for documents matching: '{filename_pattern}'")
    print("=" * 60)
    
    # 1. Check PostgreSQL - Document
    async with async_session_maker() as session:
        # Find document
        result = await session.execute(
            select(Document).where(Document.filename.ilike(f"%{filename_pattern}%"))
        )
        docs = result.scalars().all()
        
        if not docs:
            print("❌ No documents found matching pattern")
            return
        
        for doc in docs:
            print(f"\n📄 DOCUMENT: {doc.filename}")
            print("-" * 60)
            print(f"  ID: {doc.id}")
            print(f"  Tenant: {doc.tenant_id}")
            print(f"  Status: {doc.status}")
            print(f"  Summary: {doc.summary[:100] + '...' if doc.summary else '❌ EMPTY'}")
            print(f"  Document Type: {doc.document_type or '❌ EMPTY'}")
            print(f"  Keywords: {doc.keywords if doc.keywords else '❌ EMPTY'}")
            print(f"  Hashtags: {doc.hashtags if doc.hashtags else '❌ EMPTY'}")
            
            # 2. Check Chunks in PostgreSQL
            chunk_result = await session.execute(
                select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
            )
            chunk_count = chunk_result.scalar()
            
            # Sample chunk content
            sample_chunk = await session.execute(
                select(Chunk).where(Chunk.document_id == doc.id).limit(1)
            )
            sample = sample_chunk.scalars().first()
            
            print(f"\n📦 CHUNKS (PostgreSQL):")
            print(f"  Count: {chunk_count}")
            if sample:
                print(f"  Sample Content: {sample.content[:100]}...")
                print(f"  Embedding Status: {sample.embedding_status}")
            
            # 3. Check Milvus
            print(f"\n🔢 VECTORS (Milvus):")
            try:
                milvus_config = MilvusConfig(
                    host=settings.db.milvus_host,
                    port=settings.db.milvus_port,
                    collection_name=f"amber_{doc.tenant_id}"
                )
                store = MilvusVectorStore(milvus_config)
                await store.connect()
                
                # Query chunks by document_id
                chunks = await store.get_chunks([sample.id] if sample else [])
                
                # Search with dummy vector to count
                dummy_vector = [0.001] * 1536
                results = await store.search(
                    query_vector=dummy_vector,
                    tenant_id=doc.tenant_id,
                    document_ids=[doc.id],
                    limit=100
                )
                print(f"  Vectors found: {len(results)}")
                if results:
                    has_content = sum(1 for r in results if r.metadata.get("content"))
                    print(f"  With content: {has_content}")
                    print(f"  Empty content: {len(results) - has_content}")
                
                await store.disconnect()
            except Exception as e:
                print(f"  ❌ Error: {e}")
            
            # 4. Check Neo4j - Entities & Relationships
            print(f"\n🕸️ KNOWLEDGE GRAPH (Neo4j):")
            try:
                neo4j = Neo4jClient()
                
                # Count entities for this document
                entity_query = """
                MATCH (e:Entity)
                WHERE $doc_id IN e.source_chunks
                RETURN count(e) as count
                """
                entity_result = await neo4j.execute_read(entity_query, {"doc_id": doc.id})
                entity_count = entity_result[0]["count"] if entity_result else 0
                print(f"  Entities: {entity_count}")
                
                # Count relationships
                rel_query = """
                MATCH (e1:Entity)-[r]->(e2:Entity)
                WHERE $doc_id IN e1.source_chunks OR $doc_id IN e2.source_chunks
                RETURN count(r) as count
                """
                rel_result = await neo4j.execute_read(rel_query, {"doc_id": doc.id})
                rel_count = rel_result[0]["count"] if rel_result else 0
                print(f"  Relationships: {rel_count}")
                
                # Count communities
                comm_query = """
                MATCH (c:Community {tenant_id: $tenant_id})
                RETURN count(c) as count
                """
                comm_result = await neo4j.execute_read(comm_query, {"tenant_id": doc.tenant_id})
                comm_count = comm_result[0]["count"] if comm_result else 0
                print(f"  Communities (tenant-wide): {comm_count}")
                
                # Sample entities
                sample_entities_query = """
                MATCH (e:Entity)
                WHERE $doc_id IN e.source_chunks
                RETURN e.name, e.type LIMIT 5
                """
                sample_entities = await neo4j.execute_read(sample_entities_query, {"doc_id": doc.id})
                if sample_entities:
                    print(f"  Sample Entities:")
                    for ent in sample_entities:
                        print(f"    - {ent['e.name']} ({ent['e.type']})")
                
                await neo4j.close()
            except Exception as e:
                print(f"  ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Check complete")


if __name__ == "__main__":
    pattern = sys.argv[1] if len(sys.argv) > 1 else "Carbonio"
    asyncio.run(check_document(pattern))
