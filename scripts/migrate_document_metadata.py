
import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import select

from src.api.config import settings
from src.core.database.session import configure_database, get_session_maker
from src.core.ingestion.domain.document import Document

# Configure database
# Use localhost:5433 since we are running from host/shell and postgres is mapped there
db_url = settings.db.database_url.replace("@postgres:5432", "@localhost:5433")
configure_database(db_url)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate():
    logger.info("Starting document metadata migration...")

    session_factory = get_session_maker()
    async with session_factory() as session:
        result = await session.execute(select(Document))
        documents = result.scalars().all()

        logger.info(f"Found {len(documents)} documents to migrate.")

        migrated_count = 0

        for doc in documents:
            try:
                old_meta = doc.metadata_ or {}
                logger.info(f"Processing {doc.id} (filename: {doc.filename})")
                logger.info(f"  Old metadata keys: {list(old_meta.keys())}")

                # 1. Calculate new fields
                file_ext = doc.filename.split('.')[-1] if '.' in doc.filename else ""
                fmt = "PDF" if file_ext.lower() == "pdf" else file_ext.upper()

                # Created At & Upload Time
                # Convert to local time (CET)
                local_dt = doc.created_at.astimezone()
                created_date = local_dt.strftime("%d/%m/%Y")
                upload_time = local_dt.strftime("%H:%M")

                # 2. Build new metadata
                new_meta = {
                    # Preserve page count if exists
                    "pageCount": old_meta.get("page_count"),

                    # New fields
                    "title": doc.filename.rsplit('.', 1)[0],
                    "format": fmt,
                    "creationDate": created_date,
                    "uploadTime": upload_time,

                    # New fields (initialized to None for existing docs)
                    "uploadDuration": None,
                    "embeddingModel": None,
                    "llmModel": None,
                    "vectorStore": None,

                    # Technical preservation
                    "content_type": old_meta.get("content_type") or old_meta.get("mime_type"),
                    "mime_type": old_meta.get("mime_type") or old_meta.get("content_type"),
                    "file_size": old_meta.get("file_size"),
                }

                # Update
                doc.metadata_ = new_meta
                migrated_count += 1
                logger.info(f"Migrated document {doc.id}: {doc.filename}")

            except Exception as e:
                logger.error(f"Failed to migrate document {doc.id}: {e}")

        if migrated_count > 0:
            await session.commit()
            logger.info(f"Successfully migrated {migrated_count} documents.")
        else:
            logger.info("No documents needed migration.")

if __name__ == "__main__":
    asyncio.run(migrate())
