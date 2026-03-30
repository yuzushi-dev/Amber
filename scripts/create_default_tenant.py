import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import select

from src.core.database.session import async_session_maker
from src.core.models.tenant import Tenant
from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL, DEFAULT_LLM_MODEL


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
                        "embedding_model": DEFAULT_EMBEDDING_MODEL["openai"],
                        "generation_model": DEFAULT_LLM_MODEL["openai"],
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
