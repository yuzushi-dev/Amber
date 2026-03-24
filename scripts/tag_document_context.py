#!/usr/bin/env python3
"""
Tag Documents with Context Metadata
====================================

One-time script to tag existing documents with product_context and audience
metadata based on filename patterns. This adds fields to the existing JSONB
metadata without altering other metadata fields.

Usage:
    # Dry run (preview only):
    python scripts/tag_document_context.py

    # Apply changes:
    python scripts/tag_document_context.py --apply
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text


# ─── Classification Rules ───────────────────────────────────────────────────

def classify_document(filename: str) -> dict:
    """
    Classify a document by filename into product_context and audience.

    Returns dict with product_context, audience, and doc_section keys.
    """
    if filename.startswith("Carbonio_Docs_"):
        # All Carbonio_Docs_ files are from the commercial Carbonio Admin Guide
        product = "carbonio"

        if "admincli_" in filename or "cli_commands_" in filename:
            audience = "admin_cli"
            section = "cli_reference" if "cli_commands_" in filename else "admin_cli_guide"
        elif "adminpanel_" in filename:
            audience = "admin_panel"
            section = "admin_panel_guide"
        elif "architecture_" in filename:
            audience = "admin"
            section = "architecture"
        elif "install_" in filename:
            audience = "admin"
            section = "installation"
        elif "upgrade_" in filename:
            audience = "admin"
            section = "upgrade"
        elif "monitor_" in filename:
            audience = "admin"
            section = "monitoring"
        elif "develop_" in filename:
            audience = "developer"
            section = "development"
        elif "changelog_" in filename:
            audience = "admin"
            section = "changelog"
        elif "basics_" in filename or "glossary" in filename or "index" in filename:
            audience = "admin"
            section = "general"
        else:
            audience = "admin"
            section = "general"

        return {
            "product_context": product,
            "audience": audience,
            "doc_section": section,
        }
    else:
        # Non-Carbonio_Docs_ files are Zendesk KB articles (mixed context)
        return {
            "product_context": "mixed",
            "audience": "mixed",
            "doc_section": "knowledge_base",
        }


async def main():
    parser = argparse.ArgumentParser(description="Tag documents with context metadata")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry run)")
    args = parser.parse_args()

    # Initialize Database
    from src.api.config import settings
    from src.core.database.session import configure_database

    configure_database(
        database_url=settings.db.database_url,
        pool_size=settings.db.pool_size,
        max_overflow=settings.db.max_overflow,
    )

    # Import DB session
    from src.core.database.session import async_session_maker

    async with async_session_maker() as session:
        # Fetch all documents
        result = await session.execute(
            text("SELECT id, filename, metadata FROM documents ORDER BY filename")
        )
        rows = result.fetchall()

        print(f"\nFound {len(rows)} documents\n")

        # Classify and prepare updates
        stats = {}
        updates = []

        for doc_id, filename, metadata in rows:
            classification = classify_document(filename)
            key = f"{classification['product_context']}/{classification['audience']}/{classification['doc_section']}"
            stats[key] = stats.get(key, 0) + 1

            # Check if already tagged
            if metadata and metadata.get("product_context") == classification["product_context"]:
                continue

            updates.append((doc_id, filename, classification))

        # Print classification summary
        print("Classification summary:")
        print(f"{'Category':<50} {'Count':>6}")
        print("-" * 58)
        for key in sorted(stats.keys()):
            print(f"  {key:<48} {stats[key]:>6}")
        print("-" * 58)
        print(f"  {'TOTAL':<48} {len(rows):>6}")
        print(f"  {'Need update':<48} {len(updates):>6}")
        print()

        if not updates:
            print("All documents are already tagged. Nothing to do.")
            return

        if not args.apply:
            print("DRY RUN — no changes made. Use --apply to update the database.")
            print("\nSample updates:")
            for doc_id, filename, classification in updates[:5]:
                print(f"  {filename[:60]:<62} → {classification}")
            if len(updates) > 5:
                print(f"  ... and {len(updates) - 5} more")
            return

        # Apply updates
        print("Applying metadata updates...")
        count = 0
        for doc_id, filename, classification in updates:
            context_json = {
                "product_context": classification["product_context"],
                "audience": classification["audience"],
                "doc_section": classification["doc_section"],
            }
            import json

            await session.execute(
                text("""
                    UPDATE documents
                    SET metadata = metadata || CAST(:context_data AS JSONB)
                    WHERE id = :doc_id
                """),
                {
                    "doc_id": doc_id,
                    "context_data": json.dumps(context_json),
                },
            )
            count += 1

        await session.commit()
        print(f"\n✅ Updated {count} documents with context metadata.")


if __name__ == "__main__":
    asyncio.run(main())
