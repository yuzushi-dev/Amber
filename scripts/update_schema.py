
import asyncio
import logging
import sys

from sqlalchemy import text

from src.api.deps import _async_session_maker

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def update_schema():
    """
    Manually update the database schema to support folders:
    1. Create 'folders' table if not exists.
    2. Add 'folder_id' column to 'documents' table if not exists.
    """
    async with _async_session_maker() as session:
        logger.info("Checking database schema...")

        # 1. Create folders table
        # We execute statements separately because asyncpg doesn't support multiple statements in one call
        logger.info("Creating 'folders' table...")
        await session.execute(text("""
        CREATE TABLE IF NOT EXISTS folders (
            id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc') NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc') NOT NULL
        )
        """))

        await session.execute(text("CREATE INDEX IF NOT EXISTS ix_folders_id ON folders (id)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS ix_folders_tenant_id ON folders (tenant_id)"))
        logger.info("Ensured 'folders' table exists.")

        # 2. Add folder_id to documents
        check_col_sql = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='documents' AND column_name='folder_id'
        """
        result = await session.execute(text(check_col_sql))
        if not result.scalar():
            logger.info("Adding 'folder_id' column to 'documents' table...")
            await session.execute(text("ALTER TABLE documents ADD COLUMN folder_id VARCHAR REFERENCES folders(id)"))
            await session.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_folder_id ON documents (folder_id)"))
            logger.info("Added 'folder_id' column.")
        else:
            logger.info("'folder_id' column already exists.")

        await session.commit()
        logger.info("Schema update complete.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(update_schema())
