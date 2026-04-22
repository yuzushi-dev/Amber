
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.config import settings
from src.core.models.memory import ConversationSummary


async def list_conversations():
    print(f"Connecting to DB: {settings.db.database_url}")
    engine = create_async_engine(settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        query = select(ConversationSummary)
        result = await session.execute(query)
        rows = result.scalars().all()

        print(f"Found {len(rows)} conversation summaries.")
        for row in rows:
            print(f"- ID: {row.id}")
            print(f"  Title: {row.title}")
            print(f"  Tenant: {row.tenant_id}")
            print(f"  User: {row.user_id}")
            print(f"  Created: {row.created_at}")
            print(f"  Metadata: {row.metadata_}")
            print("---")

if __name__ == "__main__":
    asyncio.run(list_conversations())
