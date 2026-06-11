#!/usr/bin/env python3
"""Backfill contextual enrichment for an existing tenant corpus.

Re-runs the ContextualEnricher over chunks already in Postgres/Milvus (documents
ingested BEFORE contextual enrichment existed), then re-embeds (dense + sparse)
and upserts the enriched content. Run inside the API container::

    python3 scripts/backfill_contextual_enrichment.py --tenant hotpotbig \
        --collection amber_hotpotbig --corpus /tmp/hotpot250_corpus.md \
        --provider ollama_cloud --model gpt-oss:120b

Note: Neo4j chunk text is NOT updated (graph search modes unaffected by the
embedding-side enrichment; backbone consistency is by chunk id, not text).
"""
import argparse
import asyncio
import json
import sys
import time
import urllib.request
from types import SimpleNamespace

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from src.amber_platform.composition_root import configure_settings, get_settings  # noqa: E402
from src.api.config import settings as _settings  # noqa: E402

configure_settings(_settings)

from src.core.generation.infrastructure.providers.factory import init_providers  # noqa: E402
from src.core.ingestion.application.chunking.contextual import ContextualEnricher  # noqa: E402


def _init_factory(s):
    init_providers(
        openai_api_key=s.openai_api_key,
        anthropic_api_key=s.anthropic_api_key,
        ollama_base_url=s.ollama_base_url,
        default_llm_provider=s.default_llm_provider,
        default_llm_model=s.default_llm_model,
        default_embedding_provider=s.default_embedding_provider,
        default_embedding_model=s.default_embedding_model,
        llm_fallback_local=s.llm_fallback_local,
        llm_fallback_economy=s.llm_fallback_economy,
        llm_fallback_standard=s.llm_fallback_standard,
        llm_fallback_premium=s.llm_fallback_premium,
        embedding_fallback_order=s.embedding_fallback_order,
        openrouter_api_key=s.openrouter_api_key,
        openrouter_base_url=s.openrouter_base_url,
        nvidia_nim_api_key=s.nvidia_nim_api_key,
        nvidia_nim_base_url=s.nvidia_nim_base_url,
        llm_fallback_enabled=s.llm_fallback_enabled,
        ollama_cloud_base_url=s.ollama_cloud_base_url,
        ollama_cloud_api_keys=s.ollama_cloud_api_keys,
    )


def _embed_dense(texts, base_url, model):
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    req = urllib.request.Request(
        f"{base}/embeddings",
        data=json.dumps({"model": model, "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return [row["embedding"] for row in d["data"]]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--collection", required=True)
    ap.add_argument("--corpus", required=True, help="path to the original extracted document text")
    ap.add_argument("--provider", default="ollama_cloud")
    ap.add_argument("--model", default="gpt-oss:120b")
    ap.add_argument("--embedding-model", default="nomic-embed-text")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    _init_factory(s)
    # Usage logging inside the provider needs the DB configured (best-effort).
    try:
        from src.core.database.session import configure_database

        configure_database(database_url=s.db.app_database_url or s.db.database_url)
    except Exception:
        pass
    corpus = open(args.corpus, encoding="utf-8").read()

    import asyncpg

    db_url = (s.db.database_url or "").replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_url)
    await conn.execute(f"SET app.current_tenant = '{args.tenant}'")
    await conn.execute("SET app.is_super_admin = 'true'")
    rows = await conn.fetch(
        "SELECT id, document_id, content, metadata FROM chunks WHERE tenant_id = $1 ORDER BY index",
        args.tenant,
    )
    if args.limit:
        rows = rows[: args.limit]
    print(f"chunks: {len(rows)}", flush=True)

    chunk_objs = []
    for r in rows:
        meta = json.loads(r["metadata"]) if isinstance(r["metadata"], str) else dict(r["metadata"])
        if meta.get("context_prefix"):
            continue  # already enriched
        chunk_objs.append(
            SimpleNamespace(
                id=r["id"], document_id=r["document_id"], content=r["content"], metadata_=meta
            )
        )
    print(f"to enrich: {len(chunk_objs)}", flush=True)
    if args.dry_run:
        await conn.close()
        return

    enricher = ContextualEnricher(max_concurrency=args.concurrency)
    tenant_config = {
        "llm_steps": {
            "ingestion.chunk_context": {"provider": args.provider, "model": args.model}
        }
    }
    t0 = time.time()
    enriched_n = await enricher.enrich_chunks(
        chunk_objs, corpus, tenant_config=tenant_config, settings=s
    )
    print(f"enriched {enriched_n}/{len(chunk_objs)} in {time.time()-t0:.0f}s", flush=True)

    enriched = [c for c in chunk_objs if c.metadata_.get("context_prefix")]
    if not enriched:
        print("nothing enriched, abort before write", flush=True)
        await conn.close()
        return

    from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService

    sparse_svc = SparseEmbeddingService()
    from pymilvus import Collection, connections

    connections.connect(host=s.db.milvus_host, port=str(s.db.milvus_port))
    col = Collection(args.collection)
    col.load()

    BATCH = 32
    for i in range(0, len(enriched), BATCH):
        batch = enriched[i : i + BATCH]
        texts = [c.content for c in batch]
        dense = _embed_dense(texts, s.ollama_base_url, args.embedding_model)
        sparse = sparse_svc.embed_batch(texts)
        col.upsert(
            [
                {
                    "chunk_id": c.id,
                    "document_id": c.document_id,
                    "tenant_id": args.tenant,
                    "content": c.content[:65530],
                    "vector": d,
                    "sparse_vector": sp or {1: 0.0001},
                }
                for c, d, sp in zip(batch, dense, sparse, strict=True)
            ]
        )
        for c in batch:
            await conn.execute(
                "UPDATE chunks SET content = $1, metadata = $2::jsonb WHERE id = $3",
                c.content,
                json.dumps(c.metadata_),
                c.id,
            )
        print(f"written {i + len(batch)}/{len(enriched)}  {time.time()-t0:.0f}s", flush=True)

    col.flush()
    await conn.close()
    print("done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
