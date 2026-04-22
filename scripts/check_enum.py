
import asyncio

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.api.config import settings

load_dotenv()

async def check():
    db_url = settings.db.database_url.replace("postgres:5432", "localhost:5433")
    engine = create_async_engine(db_url)

    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT unnest(enum_range(NULL::documentstatus))"))
        print(res.scalars().all())

if __name__ == "__main__":
    asyncio.run(check())
