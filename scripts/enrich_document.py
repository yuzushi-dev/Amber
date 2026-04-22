
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.config import settings
from src.core.graph.enrichment import graph_enricher
from src.core.models.chunk import Chunk
from src.core.models.document import Document
from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def enrich_document(filename_pattern: str):
    print(f"Connecting to DB: {settings.db.database_url}")
    engine = create_async_engine(settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 1. Find Document
        query = select(Document).where(Document.filename.ilike(f"%{filename_pattern}%"))
        result = await session.execute(query)
        documents = result.scalars().all()

        if not documents:
            print(f"No documents found matching '{filename_pattern}'")
            return

        if len(documents) > 1:
            print("Found multiple documents. Using the first one:")
            for d in documents:
                print(f" - {d.id}: {d.filename}")

        document = documents[0]
        print(f"Enriching Document: {document.filename} ({document.id})")

        # 2. Fetch Chunks
        chunk_query = select(Chunk).where(Chunk.document_id == document.id)
        chunk_result = await session.execute(chunk_query)
        chunks = chunk_result.scalars().all()
        print(f"Found {len(chunks)} chunks.")

        # 3. Retrieve Embeddings from Milvus and Create Edges
        # Initialize Milvus Client
        if not document.tenant_id:
            print("Warning: Document has no tenant_id, defaulting to 'default'")
            tenant_id = "default"
        else:
            tenant_id = document.tenant_id

        print(f"DEBUG: Tenant ID: {tenant_id}")

        # Setup Milvus
        milvus_config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name=f"amber_{tenant_id}",
        )
        print(f"DEBUG: Connecting to Milvus collection: {milvus_config.collection_name}")
        milvus_client = MilvusVectorStore(milvus_config)

        try:
            # Fetch all embeddings for chunks
            chunk_ids = [c.id for c in chunks]
            print(f"Fetching embeddings for {len(chunks)} chunks...")

            # Using get_chunks is efficient enough
            all_results = []
            batch_size = 100

            for i in range(0, len(chunk_ids), batch_size):
                batch = chunk_ids[i:i+batch_size]
                res = await milvus_client.get_chunks(batch)
                all_results.extend(res)

            print(f"Retrieved {len(all_results)} embeddings from Milvus.")

            # Map retrieved embeddings back to chunk objects
            # We need to pass objects with .id and .embedding to the enricher
            chunks_with_embeddings = []

            # Create a lookup map
            embedding_map = {}
            for res in all_results:
                c_id = res.get("chunk_id")
                vec = res.get("vector")
                if c_id and vec:
                    embedding_map[c_id] = vec

            # Populate chunks
            for chunk in chunks:
                if chunk.id in embedding_map:
                    # We can just attach it dynamically or create a struct
                    # The enricher expects objects with .id and .embedding
                    chunk.embedding = embedding_map[chunk.id]
                    chunks_with_embeddings.append(chunk)
                else:
                    print(f"Warning: No embedding found for chunk {chunk.id}")

            print(f"Ready to enrich {len(chunks_with_embeddings)} chunks.")

            # 4. Create Intra-Document Similarities
            # Using the new robust in-memory method
            count = await graph_enricher.create_intra_document_similarities(
                chunks_with_embeddings,
                threshold=0.7, # Back to standard threshold
                limit=5
            )

            print(f"Created {count} similarity edges.")

        finally:
            await milvus_client.disconnect()

    await engine.dispose()
    print("Done.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/enrich_document.py <filename_pattern>")
        sys.exit(1)

    asyncio.run(enrich_document(sys.argv[1]))
