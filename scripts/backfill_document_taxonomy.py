"""
Backfill Document Taxonomy
===========================

Stamps taxonomy metadata onto existing documents that were ingested before
the taxonomy classifier was introduced, using folder name and filename rules.

Usage::

    # Dry-run (default, safe — prints what would change, writes nothing)
    python scripts/backfill_document_taxonomy.py

    # Write mode (modifies documents.metadata_ in Postgres)
    python scripts/backfill_document_taxonomy.py --write

    # Limit to a single tenant
    python scripts/backfill_document_taxonomy.py --tenant default

    # Show documents that will be left as 'unknown' for manual review
    python scripts/backfill_document_taxonomy.py --show-unknown
"""

import argparse
import asyncio
import logging
import os
import sys
from collections import defaultdict

sys.path.append(os.getcwd())

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


async def _run(write: bool, tenant_id: str | None, show_unknown: bool):
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings
    from src.core.ingestion.application.document_taxonomy import classify_document_taxonomy
    from src.core.ingestion.domain.chunk import Chunk  # noqa: F401 — triggers mapper registration
    from src.core.ingestion.domain.document import Document
    from src.core.ingestion.domain.document_share import DocumentShare  # noqa: F401
    from src.core.ingestion.domain.folder import Folder

    engine = create_async_engine(settings.db.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    mode = "WRITE" if write else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Backfill Document Taxonomy  [{mode}]")
    print(f"{'='*60}\n")

    async with async_session() as session:
        # Set super-admin context to see all tenants
        await session.execute(
            __import__("sqlalchemy").text(
                "SELECT set_config('app.is_super_admin', 'true', false)"
            )
        )

        # Load all folders for name lookup
        folder_rows = await session.execute(select(Folder.id, Folder.name))
        folder_map: dict[str, str] = {row.id: row.name for row in folder_rows}

        # Query documents
        stmt = select(Document)
        if tenant_id:
            stmt = stmt.where(Document.tenant_id == tenant_id)

        result = await session.execute(stmt)
        documents = list(result.scalars().all())

    await engine.dispose()

    # --- Classify ---
    buckets: dict[str, list[str]] = defaultdict(list)  # bucket_key -> [doc_ids]
    updates: list[tuple[str, dict]] = []  # (doc_id, new_metadata)
    already_stamped = 0
    unknown_docs: list[tuple[str, str, str]] = []  # (doc_id, filename, tenant_id)
    skipped_no_folder = 0

    for doc in documents:
        if not doc.folder_id:
            skipped_no_folder += 1
            continue

        existing_taxonomy = (doc.metadata_ or {}).get("taxonomy")

        folder_name = folder_map.get(doc.folder_id)
        taxonomy = classify_document_taxonomy(
            folder_name=folder_name,
            document_title=doc.filename,
        )

        bucket = f"{taxonomy['edition']}/{taxonomy['audience']}/{taxonomy['source_family']}"
        buckets[bucket].append(doc.id)

        if taxonomy["edition"] == "unknown":
            unknown_docs.append((doc.id, doc.filename, doc.tenant_id))

        if existing_taxonomy == taxonomy:
            already_stamped += 1
            continue

        new_meta = dict(doc.metadata_ or {})
        new_meta["taxonomy"] = taxonomy
        updates.append((doc.id, new_meta))

    # --- Report ---
    print(f"Total documents scanned: {len(documents)}")
    print(f"Skipped (no folder): {skipped_no_folder}")
    print(f"Already correctly stamped: {already_stamped}")
    print(f"Documents to update: {len(updates)}\n")

    print("Taxonomy bucket distribution:")
    for bucket, ids in sorted(buckets.items()):
        print(f"  {bucket:<45}  {len(ids):>4} docs")

    print(f"\nUnknown taxonomy docs: {len(unknown_docs)}")

    if show_unknown and unknown_docs:
        print("\nUnknown docs (no folder or unrecognised folder):")
        for doc_id, filename, tid in unknown_docs[:50]:
            print(f"  [{tid}] {doc_id[:16]}…  {filename}")
        if len(unknown_docs) > 50:
            print(f"  ... and {len(unknown_docs) - 50} more")

    if not write:
        print("\n[DRY-RUN] No changes written. Re-run with --write to apply.\n")
        return

    if not updates:
        print("\nNothing to update.\n")
        return

    # --- Apply updates ---
    print(f"\nApplying {len(updates)} updates...")
    engine2 = create_async_engine(settings.db.database_url, echo=False)
    async_session2 = sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)

    BATCH = 200
    updated = 0
    async with async_session2() as session:
        await session.execute(
            __import__("sqlalchemy").text(
                "SELECT set_config('app.is_super_admin', 'true', false)"
            )
        )
        for i in range(0, len(updates), BATCH):
            batch = updates[i : i + BATCH]
            for doc_id, new_meta in batch:
                await session.execute(
                    update(Document)
                    .where(Document.id == doc_id)
                    .values(metadata_=new_meta)
                )
            await session.commit()
            updated += len(batch)
            print(f"  {updated}/{len(updates)} updated...")

    await engine2.dispose()
    print(f"\nDone. {updated} documents stamped with taxonomy.\n")


def main():
    parser = argparse.ArgumentParser(description="Backfill document taxonomy metadata.")
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="Apply changes to the database (default: dry-run only)",
    )
    parser.add_argument(
        "--tenant",
        default=None,
        help="Limit to a specific tenant ID",
    )
    parser.add_argument(
        "--show-unknown",
        action="store_true",
        default=False,
        help="Print the list of documents that resolve to unknown taxonomy",
    )
    args = parser.parse_args()
    asyncio.run(_run(write=args.write, tenant_id=args.tenant, show_unknown=args.show_unknown))


if __name__ == "__main__":
    main()
