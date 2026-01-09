
import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.core.models.base import Base
from src.core.models.usage import UsageLog
from sqlalchemy.ext.asyncio import create_async_engine
from src.api.config import settings

async def init_db():
    print(f"Connecting to {settings.db.database_url}")
    engine = create_async_engine(settings.db.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Tables created")

if __name__ == "__main__":
    asyncio.run(init_db())
