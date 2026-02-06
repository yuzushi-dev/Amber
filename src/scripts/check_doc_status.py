import asyncio
import sys

sys.path.append("/app")

from sqlalchemy import select

from src.api.config import settings
from src.api.deps import _get_async_session_maker
from src.core.database.session import configure_database
from src.core.ingestion.domain.document import Document

configure_database(str(settings.db.database_url))


async def main():
    async_session = _get_async_session_maker()
    async with async_session() as session:
        # Get latest document
        result = await session.execute(
            select(Document).order_by(Document.created_at.desc()).limit(1)
        )
        doc = result.scalars().first()

        if doc:
            print(f"Document ID: {doc.id}")
            print(f"Status: {doc.status}")
            print(f"Created At: {doc.created_at}")
            print(f"Error Message: {doc.error_message}")
        else:
            print("No documents found.")


if __name__ == "__main__":
    asyncio.run(main())
