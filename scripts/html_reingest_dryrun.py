#!/usr/bin/env python3
"""
Dry-run: trova documenti HTML che necessitano re-ingest dopo fix HtmlExtractor.

Uso:
    python scripts/html_reingest_dryrun.py --db-url postgresql+asyncpg://...
    # oppure via daily.py tunnel:
    python daily_html_dryrun.py
"""

import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


async def run(db_url: str) -> None:
    engine = create_async_engine(db_url, echo=False)
    async with AsyncSession(engine) as session:

        # ---- 1. Totale HTML docs ----
        total = (await session.execute(text("""
            SELECT count(*) FROM documents
            WHERE filename ILIKE '%.html' OR filename ILIKE '%.htm'
               OR storage_path ILIKE '%.html' OR storage_path ILIKE '%.htm'
        """))).scalar()

        # ---- 2. Distribuzione per chunk count ----
        dist = (await session.execute(text("""
            SELECT chunk_count, count(*) AS num_docs
            FROM (
                SELECT d.id, count(c.id) AS chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                WHERE d.filename ILIKE '%.html' OR d.filename ILIKE '%.htm'
                   OR d.storage_path ILIKE '%.html' OR d.storage_path ILIKE '%.htm'
                GROUP BY d.id
            ) sub
            GROUP BY chunk_count
            ORDER BY chunk_count
        """))).fetchall()

        # ---- 3. Docs con content='None' (estrazione fallita) ----
        none_docs = (await session.execute(text("""
            SELECT d.id, d.tenant_id, d.filename, d.storage_path
            FROM documents d
            JOIN chunks c ON c.document_id = d.id AND c.index = 0
            WHERE (d.filename ILIKE '%.html' OR d.storage_path ILIKE '%.html')
            AND c.content = 'None'
            ORDER BY d.created_at DESC
        """))).fetchall()

        # ---- 4. Docs 1-chunk con contenuto corto (< 200 chars) ----
        short_docs = (await session.execute(text("""
            SELECT d.id, d.tenant_id, d.filename, length(c.content) AS clen,
                   left(c.content, 120) AS preview
            FROM documents d
            JOIN chunks c ON c.document_id = d.id AND c.index = 0
            WHERE (d.filename ILIKE '%.html' OR d.storage_path ILIKE '%.html')
            AND (SELECT count(*) FROM chunks WHERE document_id = d.id) = 1
            AND length(c.content) > 4 AND length(c.content) < 200
            ORDER BY clen ASC
            LIMIT 30
        """))).fetchall()

        # ---- 5. Docs per tenant ----
        by_tenant = (await session.execute(text("""
            SELECT d.tenant_id, count(*) AS num_docs
            FROM documents d
            WHERE d.filename ILIKE '%.html' OR d.storage_path ILIKE '%.html'
            GROUP BY d.tenant_id
            ORDER BY num_docs DESC
        """))).fetchall()

        # ---- 6. Cerca specificamente docs con parole chiave release notes ----
        release_docs = (await session.execute(text("""
            SELECT d.id, d.tenant_id, d.filename,
                   (SELECT count(*) FROM chunks WHERE document_id = d.id) AS nchunks,
                   (SELECT left(content, 200) FROM chunks WHERE document_id = d.id AND index = 0) AS preview
            FROM documents d
            WHERE (d.filename ILIKE '%.html' OR d.storage_path ILIKE '%.html')
            AND (d.filename ILIKE '%release%' OR d.filename ILIKE '%Release%'
                OR d.filename ILIKE '%version%' OR d.filename ILIKE '%changelog%')
            ORDER BY d.created_at DESC
        """))).fetchall()

    await engine.dispose()

    # ==================== OUTPUT ====================

    print("=" * 80)
    print(f"HTML DOCUMENTS DRY-RUN REPORT")
    print("=" * 80)
    print(f"\nTotale doc HTML: {total}")

    print(f"\n--- Distribuzione per numero di chunk ---")
    one_chunk = 0
    zero_chunk = 0
    for row in dist:
        marker = " <-- " if row.chunk_count <= 1 else ""
        print(f"  {row.chunk_count:>4} chunks: {row.num_docs:>5} docs  ({row.num_docs/total*100:.1f}%){marker}")
        if row.chunk_count == 1:
            one_chunk = row.num_docs
        if row.chunk_count == 0:
            zero_chunk = row.num_docs

    print(f"\n--- Per tenant ---")
    for row in by_tenant:
        print(f"  {row.tenant_id[:36]:<36}  {row.num_docs:>5} docs")

    print(f"\n--- Docs con estrazione fallita (content='None') [{len(none_docs)}] ---")
    for row in none_docs:
        print(f"  {row.id}  {row.tenant_id[:12]:<12}  {row.filename[:60]}")

    print(f"\n--- Docs 1-chunk con contenuto corto < 200 chars [{len(short_docs)}] ---")
    for row in short_docs:
        print(f"  {row.id}  len={row.clen:4}  {row.filename[:50]}")
        print(f"           {row.preview!r}")

    print(f"\n--- Docs con 'release' o 'version' nel filename [{len(release_docs)}] ---")
    for row in release_docs:
        print(f"  {row.id}  chunks={row.nchunks:3}  {row.filename[:60]}")
        if row.preview:
            print(f"           {row.preview[:120]!r}")

    print("\n" + "=" * 80)
    print("STIMA IMPATTO RE-INGEST:")
    print(f"  Docs con content='None' (falliti):       {len(none_docs):>5}  → re-ingest certo")
    print(f"  Docs 1-chunk contenuto corto:            {one_chunk:>5}  → da verificare")
    print(f"  Docs release/version (più rischio):      {len(release_docs):>5}  → da verificare")
    print(f"  Totale HTML (worst case):                {total:>5}  → re-ingest completo")
    print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(description="HTML re-ingest dry-run")
    parser.add_argument("--db-url", required=True,
                        help="postgresql+asyncpg://user:pass@host:port/db")
    args = parser.parse_args()
    asyncio.run(run(args.db_url))


if __name__ == "__main__":
    main()
