
import asyncio
import os
import sys

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.append(os.getcwd())

from src.api.config import settings
from src.core.models.chunk import Chunk
from src.core.models.document import Document


async def check_chunks():
    engine = create_async_engine(settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get the document first
        result = await session.execute(select(Document).where(Document.id == "doc_1e54a28af3e548d6"))
        doc = result.scalars().first()
        if not doc:
            print("Document not found")
            return

        print(f"Document: {doc.filename} ({doc.id})")

        # Check chunk statuses
        result = await session.execute(
            select(Chunk.embedding_status, func.count(Chunk.id))
            .where(Chunk.document_id == doc.id)
            .group_by(Chunk.embedding_status)
        )

        print("\nChunk Status Distribution:")
        for status, count in result.all():
            print(f"  {status}: {count}")

if __name__ == "__main__":
    asyncio.run(check_chunks())
