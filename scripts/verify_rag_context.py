#!/usr/bin/env python3
"""
Verify RAG Context (Simplified)
==============================

Directly fetches chunks from the database for each document type and passes them
to ContextBuilder to verify that metadata headers (Product, Audience) are correctly
included in the context.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from src.api.config import settings
from src.core.database.session import async_session_maker, configure_database
from src.core.generation.application.context_builder import ContextBuilder
from src.core.retrieval.domain.candidate import Candidate


async def verify_type(prefix: str, label: str):
    print(f"\n--- Testing Type: {label} (prefix: {prefix}) ---")

    async with async_session_maker() as session:
        # Fetch an actual chunk from the DB
        result = await session.execute(
            text("""
                SELECT d.filename, d.metadata, c.content 
                FROM documents d 
                JOIN chunks c ON d.id = c.document_id 
                WHERE d.filename LIKE :pattern 
                LIMIT 1
            """),
            {"pattern": f"{prefix}%"}
        )
        row = result.fetchone()

        if not row:
            print(f"No document found for prefix {prefix}")
            return

        filename, metadata, content = row

        # Construct Candidate object as expected by ContextBuilder
        candidate = Candidate(
            chunk_id="test_id",
            content=content[:150].strip() + "...",
            metadata=metadata
        )

        # Build context
        builder = ContextBuilder(max_tokens=1000)
        res = builder.build([candidate])

        print(res.content)
        print("-" * 40)

async def main():
    configure_database(settings.db.database_url)

    await verify_type("CE_Docs_", "Carbonio CE Admin Guide")
    await verify_type("User_Docs_", "Carbonio User Guide")
    await verify_type("Carbonio_Docs_", "Carbonio Admin Guide")

if __name__ == "__main__":
    asyncio.run(main())
