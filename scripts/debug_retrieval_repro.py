
import asyncio
import logging
import sys
import os
from pprint import pprint

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.append(os.getcwd())

from src.amber_platform.composition_root import build_retrieval_service, platform, configure_settings
from src.api.config import settings
from src.core.database.session import configure_database

async def main():
    print("DEBUG: Configuring settings...")
    configure_settings(settings)
    configure_database(settings.db.database_url)
    
    print("DEBUG: Initializing platform...")
    await platform.initialize()
    
    try:
        from src.core.database.session import get_session_maker
        async_session_maker = get_session_maker()
        
        async with async_session_maker() as session:
            print("DEBUG: Building RetrievalService...")
            retrieval_service = build_retrieval_service(session)
            
            tenant_id = settings.tenant_id # Default tenant
            print(f"DEBUG: Using default tenant_id from settings: {tenant_id}")
            
            # Try to query
            query = "What is mesh?"
            print(f"DEBUG: Executing retrieve('{query}')...")
            
            # Need to mock request-like context usually, but RetrievalService is pure
            
            result = await retrieval_service.retrieve(
                query=query,
                tenant_id=tenant_id,
                top_k=5,
                include_trace=True
            )
            
            print(f"\nDEBUG: Retrieval Result Chunks: {len(result.chunks)}")
            if len(result.chunks) > 0:
                 print(f"\n--- FOUND {len(result.chunks)} CHUNKS ---")
                 for i, chunk in enumerate(result.chunks):
                     print(f"\n[Chunk {i+1}] (Score: {chunk.get('score', 'N/A')})")
                     print(f"Content: {chunk.get('content', '')[:200]}...")
            
            print("\nDEBUG: Trace:")
            pprint(result.trace)
            
            if not result.chunks:
                print("\nDEBUG: REPRODUCED: No chunks found.")
                
                # Try to count vectors in Milvus
                try:
                    print("\nDEBUG: Checking Vector Store stats...")
                    # Assuming MilvusVectorStore
                    vs = retrieval_service.vector_store
                    # Use internal client execution if method available, usually count isn't exposed directly in port
                    # But we can try to search with empty vector or something if query was bad
                    
                    # Or try specific query for existing doc if we knew one
                except Exception as e:
                    print(f"DEBUG: Could not check vector store stats: {e}")

            else:
                print("\nDEBUG: Documents found.")
            
    except Exception as e:
        logger.exception(f"DEBUG: Error during execution: {e}")
    finally:
        print("DEBUG: Shutting down platform...")
        await platform.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
