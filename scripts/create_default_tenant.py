import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from src.core.models.api_key import ApiKey
from src.core.models.tenant import Tenant
from src.core.database.session import async_session_maker
from sqlalchemy import select

async def main():
    try:
        async with async_session_maker() as session:
            # Check if default tenant exists
            result = await session.execute(select(Tenant).where(Tenant.id == 'default'))
            tenant = result.scalar_one_or_none()
            
            if tenant:
                print("Tenant 'default' already exists.")
            else:
                print("Creating tenant 'default' (Super User)...")
                tenant = Tenant(
                    id='default',
                    name='Super User',
                    api_key_prefix='amber_',
                    is_active=True,
                    config={
                        "embedding_model": "text-embedding-3-small",
                        "generation_model": "gpt-4o-mini",
                        "top_k": 10,
                        "expansion_depth": 2,
                        "similarity_threshold": 0.7,
                        "reranking_enabled": True,
                        "graph_expansion_enabled": True,
                        "hybrid_ocr_enabled": True
                    }
                )
                session.add(tenant)
                await session.commit()
                print("Tenant 'default' created successfully.")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
