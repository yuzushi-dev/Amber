
import asyncio
import os
import sys

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(os.getcwd())

from src.api.config import settings
from src.core.models.chunk import Chunk


async def test_routes():
    # 1. Get a chunk to test
    engine = create_async_engine(settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    chunk_id = None
    doc_id = "doc_1e54a28af3e548d6" # Carbonio User Guide

    async with async_session() as session:
        result = await session.execute(select(Chunk).where(Chunk.document_id == doc_id).limit(1))
        chunk = result.scalars().first()
        if not chunk:
            print("No chunks found")
            return
        chunk_id = chunk.id
        print(f"Testing with Chunk ID: {chunk_id}")
        print(f"Original Content: {chunk.content[:50]}...")

    # 2. Test Update (PUT)
    headers = {"X-API-Key": "amber-dev-key-2024"}
    base_url = "http://localhost:8000/v1" # Assuming port 8000

    new_content = "This is a TEST update for chunk editing functionality. " + chunk.content[:50]

    print("\nTesting PUT...")
    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{base_url}/documents/{doc_id}/chunks/{chunk_id}",
            json={"content": new_content},
            headers=headers
        )
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print(f"Response: {response.json()['content'][:50]}...")
        else:
            print(f"Error: {response.text}")

    # 3. Test Delete (DELETE) - SKIP for now to avoid destroying data unless we want to
    # print("\nTesting DELETE...")
    # async with httpx.AsyncClient() as client:
    #     response = await client.delete(
    #         f"{base_url}/documents/{doc_id}/chunks/{chunk_id}",
    #         headers=headers
    #     )
    #     print(f"Status: {response.status_code}")

if __name__ == "__main__":
    asyncio.run(test_routes())
