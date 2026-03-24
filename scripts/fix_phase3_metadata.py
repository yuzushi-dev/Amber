#!/usr/bin/env python3
"""
Fix Phase 3 Metadata and Folders
================================

Retroactively applies product_context, audience, and folder_id to Phase 3 documents
(CE Admin Guide and User Guide) that were ingested without these tags due to API
limitations in the upload endpoint.
"""

import argparse
import asyncio
import sys
import json
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Mapping prefix to (Folder ID, Product Context, Audience, Doc Section)
RULES = {
    "CE_Docs_": (
        "b0c836dd-6782-4c27-a6fb-565e300e34b4", # CEGuide folder
        "carbonio_ce",
        "admin",
        "admin_guide"
    ),
    "User_Docs_": (
        "c5891152-cc78-4136-9e71-eb33558a2a5a", # UserGuide folder
        "carbonio",
        "user",
        "user_guide"
    )
}

async def main():
    parser = argparse.ArgumentParser(description="Fix Phase 3 metadata and folder assignments")
    parser.add_argument("--apply", action="store_true", help="Apply changes to the database")
    args = parser.parse_args()

    # Initialize Database
    from src.api.config import settings
    from src.core.database.session import configure_database, async_session_maker

    configure_database(
        database_url=settings.db.database_url,
        pool_size=settings.db.pool_size,
        max_overflow=settings.db.max_overflow,
    )

    async with async_session_maker() as session:
        # Fetch all documents to check for missing Phase 3 tags
        result = await session.execute(
            text("SELECT id, filename, folder_id, metadata FROM documents")
        )
        rows = result.fetchall()

        updates = []
        for doc_id, filename, folder_id, metadata in rows:
            rule_match = None
            for prefix, rule in RULES.items():
                if filename.startswith(prefix):
                    rule_match = rule
                    break
            
            if not rule_match:
                continue
            
            target_folder, product, audience, section = rule_match
            
            # Check if update is needed
            needs_folder = folder_id != target_folder
            needs_meta = not metadata or metadata.get("product_context") != product
            
            if needs_folder or needs_meta:
                updates.append({
                    "id": doc_id,
                    "filename": filename,
                    "folder_id": target_folder,
                    "product": product,
                    "audience": audience,
                    "section": section
                })

        logger.info(f"Analyzed {len(rows)} documents.")
        if not updates:
            logger.info("All documents are correctly tagged. Nothing to do.")
            return

        logger.info(f"Found {len(updates)} documents needing updates.")

        if not args.apply:
            logger.info("DRY RUN — no changes made. Use --apply to update the database.")
            logger.info("\nSample updates:")
            for up in updates[:5]:
                logger.info(f"  {up['filename'][:40]:<42} → Folder: {up['folder_id'][:8]}..., Product: {up['product']}")
            if len(updates) > 5:
                logger.info(f"  ... and {len(updates) - 5} more")
            return

        # Apply updates in a transaction
        logger.info("Applying updates...")
        for up in updates:
            # Prepare metadata merge
            meta_update = {
                "product_context": up["product"],
                "audience": up["audience"],
                "doc_section": up["section"]
            }
            
            await session.execute(
                text("""
                    UPDATE documents
                    SET folder_id = :folder_id,
                        metadata = metadata || CAST(:meta_json AS JSONB)
                    WHERE id = :id
                """),
                {
                    "id": up["id"],
                    "folder_id": up["folder_id"],
                    "meta_json": json.dumps(meta_update)
                }
            )

        await session.commit()
        logger.info(f"Successfully updated {len(updates)} documents with correct metadata and folder assignments.")

if __name__ == "__main__":
    asyncio.run(main())
