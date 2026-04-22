
import asyncio
import os
import sys

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.append(os.getcwd())

from src.api.config import settings
from src.core.models.chunk import Chunk, EmbeddingStatus


async def fix_chunks():
    engine = create_async_engine(settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        doc_id = "doc_1e54a28af3e548d6"

        print(f"Updating chunks for document {doc_id}...")

        # Update pending/failed chunks to completed
        stmt = (
            update(Chunk)
            .where(Chunk.document_id == doc_id)
            .values(embedding_status=EmbeddingStatus.COMPLETED)
        )

        result = await session.execute(stmt)
        await session.commit()

        print(f"Updated {result.rowcount} chunks to COMPLETED.")

if __name__ == "__main__":
    asyncio.run(fix_chunks())
