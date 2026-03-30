
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from src.api.config import settings
from src.core.database.session import async_session_maker, configure_database


async def test_conn():
    print(f"Connecting to {settings.db.database_url}")
    configure_database(
        database_url=settings.db.database_url,
        pool_size=settings.db.pool_size,
        max_overflow=settings.db.max_overflow,
    )
    async with async_session_maker() as session:
        res = await session.execute(text("SELECT 1"))
        print(f"Success: {res.scalar()}")

if __name__ == "__main__":
    asyncio.run(test_conn())
