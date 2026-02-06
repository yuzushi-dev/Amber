import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.api.config import settings
from src.core.database.session import configure_database, get_session_maker
from src.core.ingestion.domain.document import Document


async def main():
    print("Configuring DB...")
    configure_database(settings.db.database_url)

    print("Initializing DB session...")
    session_maker = get_session_maker()

    filename = "Backup not Running after upgrade to Carbonio 25.6.0   Howto fix   Zextras Group.pdf"
    async with session_maker() as session:
        # Search for any document with Backup in the name
        print("Searching for documents with 'Backup' in the filename...")
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.filename.ilike("%Backup%"))
        )
        result = await session.execute(stmt)
        docs = result.scalars().all()

        if not docs:
            print("No documents found with 'Backup' in the name.")
            return

        print(f"Found {len(docs)} documents:")
        for d in docs:
            print(f" - {d.filename} (ID: {d.id}, Status: {d.status})")

        # We'll just look at the first one in detail if it matches our target
        doc = next((d for d in docs if d.filename == filename), None)
        if not doc:
            print(
                f"The specific file '{filename}' was not found in the list (this shouldn't happen if it was found before)."
            )
            return

        print("Document Found:")
        print(f"  ID: {doc.id}")
        print(f"  Tenant: {doc.tenant_id}")
        print(f"  Status: {doc.status}")
        print(f"  Domain: {doc.domain}")
        print(f"  Summary: {doc.summary}")
        print(f"  Error Message: {doc.error_message}")
        print(f"  Metadata: {doc.metadata_}")

        if doc.chunks:
            print(f"  Chunk Count: {len(doc.chunks)}")
            print("  First 3 Chunks Preview:")
            for i, chunk in enumerate(doc.chunks[:3]):
                print(f"    Chunk {i}: {chunk.content[:200]}...")
                print(f"    Embedding Status: {chunk.embedding_status}")
        else:
            print("  Chunk Count: 0")


if __name__ == "__main__":
    asyncio.run(main())
