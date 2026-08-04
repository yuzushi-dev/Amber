#!/usr/bin/env python3
"""Backfill contextual enrichment for chunks ingested before/without it.

Fixes for Issue #98 over the previous version of this script:

1. Dry-run by default (like the sibling ``backfill_document_taxonomy.py``).
   ``--write`` is required to make any change; the default run validates
   scope, provider/model, and collection and prints a per-document preview
   with zero LLM/embedding cost.
2. Scoped by document. ``--doc-ids-file``/``--document-id`` select which
   documents to touch; the query is filtered by ``document_id = ANY(...)``.
3. No more "one --corpus file for the whole tenant". Each document's own
   text is reconstructed from ITS OWN chunks
   (``COALESCE(metadata->>'original_content', content)``, ordered by
   ``index``) and used as the enrichment context for ONLY that document's
   chunks. This removes the cross-document contamination the single-corpus
   design had (including hallucinated context for chunks whose byte offsets
   fell past a mismatched corpus file's length). Offsets are recomputed
   against the reconstructed text FOR THE DURATION OF THE ENRICHMENT CALL
   ONLY and restored to their original stored values before anything is
   persisted -- the reconstruction is an approximation (chunking strips some
   whitespace/separators) and must never overwrite the true extraction-time
   offsets in Postgres/Milvus.
4. No silent fallback to a paid provider. The LLM provider is built with
   ``with_failover=False`` unless ``--allow-fallback`` is passed explicitly
   -- a cost-bearing operation across many documents must not silently
   escalate to a different, unbudgeted provider mid-run.
5. Partial success is no longer indistinguishable from success. Each
   document's enrichment yield is checked against ``--min-yield`` (default
   0.9); a document falling below it aborts the whole run BEFORE any write
   for that document, with the failure printed. (This is exactly the
   silent-degradation shape that hid issue #84 for ~3 weeks.)
6. Vector writes go through ``MilvusVectorStore.upsert_chunks`` instead of a
   raw ``pymilvus.Collection.upsert()`` call, so the embedding-dimension
   parity guard applies and the per-chunk dynamic metadata fields set at
   ingestion time (``chunk.metadata_``) are preserved instead of being wiped
   by a bare 6-field upsert.
7. Tenant id is bound as a query parameter, not interpolated into the SQL
   string.

Postgres ``chunks.content``/``metadata`` are updated via ``UPDATE ... WHERE
id = $n`` (never deleted/reinserted); Milvus is upserted by existing
``chunk_id`` (never dropped/recreated). Neo4j is not touched. The pre-
enrichment text is preserved in ``metadata->>'original_content'`` (see
``ContextualEnricher``), so a mistaken run can be reverted with a single
``UPDATE`` restoring ``content``/stripping ``context_prefix`` -- keep a
targeted snapshot of the touched rows before running with ``--write`` if you
want an even simpler rollback path; see the issue #98 operational checklist.

Run inside a CPU worker container, NOT ``amber2-api-1`` -- this script loads
SPLADE (torch) for sparse embeddings, and running that a second time inside
the API container risks host OOM under production RAM sizing.

Usage::

    # Preview only: validates scope/provider/model/collection, no LLM cost.
    python3 scripts/backfill_contextual_enrichment.py --tenant default \\
        --collection amber_default --doc-ids-file /tmp/doc_ids_98.txt

    # Actually enrich and persist.
    python3 scripts/backfill_contextual_enrichment.py --tenant default \\
        --collection amber_default --doc-ids-file /tmp/doc_ids_98.txt \\
        --provider ollama_cloud --model gpt-oss:120b --write

    # A single document, for canary verification before a full run.
    python3 scripts/backfill_contextual_enrichment.py --tenant default \\
        --collection amber_default --document-id doc_abc123 --write
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
from src.core.retrieval.infrastructure.vector_store.milvus import (  # noqa: E402
    MilvusConfig,
    MilvusVectorStore,
)
from src.shared.model_registry import LLM_MODELS  # noqa: E402


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


def _load_doc_ids(path: str) -> list[str]:
    """One document ID per line. Blank lines and '#'-led comments ignored."""
    ids: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                ids.append(line)
    return ids


def _validate_model(provider: str, model: str) -> str | None:
    """Return a warning string if `model` isn't a known entry for `provider`
    in the model registry, else None. Does not block by itself -- the caller
    decides whether an unknown model requires --force."""
    catalog = LLM_MODELS.get(provider, {})
    if model not in catalog:
        return (
            f"model '{model}' is not in the model_registry catalog for provider "
            f"'{provider}' (known: {sorted(catalog) or 'none'}). It may still work "
            "(the registry lags real provider catalogs) but this is exactly the "
            "unnoticed-retirement shape that caused issue #84 -- verify it's live "
            "before running with --write, or pass --force to proceed anyway."
        )
    return None


async def _reconstruct_documents(
    conn, tenant_id: str, doc_ids: list[str]
) -> dict[str, dict]:
    """Group this tenant's chunks by document_id (ordered by index) and
    rebuild each document's approximate original text by concatenating
    ``COALESCE(original_content, content)`` -- so chunks that are already
    enriched, or already carry some other prefix, contribute their
    PRE-prefix text rather than feeding an already-generated prefix back
    into the prompt for a sibling chunk's context.

    Returns ``{document_id: {"text": str, "chunks": [chunk_row, ...]}}``
    where each chunk_row carries recomputed ``start``/``end`` offsets into
    ``text`` for enrichment-time use only (the true, stored
    ``start_char``/``end_char`` are kept unmodified in ``metadata`` and must
    never be overwritten by these).
    """
    rows = await conn.fetch(
        """
        SELECT id, document_id, content, metadata, index
        FROM chunks
        WHERE tenant_id = $1 AND document_id = ANY($2)
        ORDER BY document_id, index
        """,
        tenant_id,
        doc_ids,
    )
    docs: dict[str, dict] = {}
    for r in rows:
        meta = json.loads(r["metadata"]) if isinstance(r["metadata"], str) else dict(r["metadata"])
        pristine = meta.get("original_content") or r["content"]
        doc = docs.setdefault(r["document_id"], {"text": "", "chunks": []})
        if doc["text"]:
            doc["text"] += "\n\n"
        start = len(doc["text"])
        doc["text"] += pristine
        end = len(doc["text"])
        doc["chunks"].append(
            {
                "id": r["id"],
                "document_id": r["document_id"],
                "content": r["content"],
                "metadata": meta,
                "reconstructed_start": start,
                "reconstructed_end": end,
            }
        )
    return docs


def _restore_original_offsets(chunk: SimpleNamespace, original: tuple) -> None:
    """Undo the temporary start_char/end_char override applied for
    enrichment (see ``_reconstruct_documents``), restoring the chunk's
    metadata to whatever it stored before -- present value or absent key.
    Must run before ANY persistence: the reconstructed offsets are only
    valid as an approximate index into the in-memory re-concatenated
    document text, never as the true extraction-time offsets.
    """
    orig_start, orig_end = original
    if orig_start is None:
        chunk.metadata_.pop("start_char", None)
    else:
        chunk.metadata_["start_char"] = orig_start
    if orig_end is None:
        chunk.metadata_.pop("end_char", None)
    else:
        chunk.metadata_["end_char"] = orig_end


def _probe_collection(
    milvus: dict, collection_name: str, vector_field_name: str
) -> tuple[bool, int | None]:
    """Check whether ``collection_name`` already exists in Milvus and, if
    so, read its real vector dimension off the live schema -- so a
    ``--collection`` typo aborts loudly instead of ``connect()`` silently
    auto-creating an empty collection under that name (issue #98, and so
    the embedding-dimension parity guard checks against reality instead of
    a hardcoded default). Returns ``(exists, dimensions)``; ``dimensions``
    is ``None`` if the collection exists but the vector field couldn't be
    found in its schema.
    """
    if not milvus["utility"].has_collection(collection_name):
        return False, None
    dimensions = None
    for field in milvus["Collection"](collection_name).schema.fields:
        if field.name == vector_field_name:
            dimensions = field.params.get("dim")
    return True, dimensions


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--collection", required=True)
    ap.add_argument("--doc-ids-file", help="path to a file with one document ID per line")
    ap.add_argument(
        "--document-id", action="append", default=[], help="repeatable; scope to one document"
    )
    ap.add_argument("--provider", default="ollama_cloud")
    ap.add_argument("--model", default="gpt-oss:120b")
    ap.add_argument("--embedding-model", default="nomic-embed-text")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument(
        "--min-yield",
        type=float,
        default=0.9,
        help="abort BEFORE writing a document's results if enriched/total falls below this",
    )
    ap.add_argument(
        "--allow-fallback",
        action="store_true",
        help="allow silent failover to other configured providers (may be paid) if --provider "
        "errors; default is to fail loudly on that provider only, since cost is not "
        "budgeted for whatever a fallback chain might escalate to",
    )
    ap.add_argument(
        "--force", action="store_true", help="proceed even if --model isn't in the model registry"
    )
    ap.add_argument("--write", action="store_true", help="required to actually enrich and persist")
    args = ap.parse_args()

    doc_ids = list(dict.fromkeys(args.document_id))  # de-dup, preserve order
    if args.doc_ids_file:
        doc_ids.extend(d for d in _load_doc_ids(args.doc_ids_file) if d not in doc_ids)
    if not doc_ids:
        print("no document IDs given (--doc-ids-file / --document-id); nothing to do", flush=True)
        return

    model_warning = _validate_model(args.provider, args.model)
    if model_warning and not args.force:
        print(f"ABORT: {model_warning}", flush=True)
        print("(pass --force to proceed anyway)", flush=True)
        raise SystemExit(1)
    if model_warning:
        print(f"WARNING (proceeding due to --force): {model_warning}", flush=True)

    s = get_settings()
    _init_factory(s)
    try:
        from src.core.database.session import configure_database

        configure_database(database_url=s.db.app_database_url or s.db.database_url)
    except Exception:
        pass

    import asyncpg

    db_url = (s.db.database_url or "").replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_url)
    await conn.execute("SELECT set_config('app.current_tenant', $1, false)", args.tenant)
    await conn.execute("SELECT set_config('app.is_super_admin', 'true', false)")

    active_collection = await conn.fetchval(
        "SELECT config->>'active_vector_collection' FROM tenants WHERE id = $1", args.tenant
    )
    if active_collection and active_collection != args.collection:
        print(
            f"WARNING: --collection '{args.collection}' does not match this tenant's "
            f"active_vector_collection '{active_collection}'. Writing to a collection "
            "the tenant doesn't actually query is a wasted, expensive no-op.",
            flush=True,
        )

    # Validated unconditionally (dry-run included, per the module docstring):
    # fail loudly on a --collection typo instead of letting
    # MilvusVectorStore.connect() silently CREATE a brand-new, empty
    # collection under that name later during --write -- which would make
    # the whole run a phantom write: Postgres gets the enriched content, the
    # collection the tenant actually queries keeps its pristine vectors, and
    # the script still prints success. Also read the real vector dimension
    # off the existing collection so the embedding-dimension parity guard in
    # upsert_chunks checks against reality, not MilvusConfig's 768 default.
    from src.core.retrieval.infrastructure.vector_store.milvus import _get_milvus

    _milvus = _get_milvus()
    _milvus["connections"].connect(alias="default", host=s.db.milvus_host, port=s.db.milvus_port)
    exists, milvus_dimensions = _probe_collection(_milvus, args.collection, MilvusVectorStore.FIELD_VECTOR)
    if not exists:
        print(
            f"ABORT: Milvus collection '{args.collection}' does not exist. Refusing to "
            "auto-create it here -- verify --collection against this tenant's "
            "active_vector_collection and that ingestion has actually run for it.",
            flush=True,
        )
        await conn.close()
        raise SystemExit(1)
    if milvus_dimensions is None:
        print(f"ABORT: could not determine the vector dimension of collection '{args.collection}'.", flush=True)
        await conn.close()
        raise SystemExit(1)
    print(f"Collection '{args.collection}' OK (dimension={milvus_dimensions}).", flush=True)
    docs = await _reconstruct_documents(conn, args.tenant, doc_ids)
    missing = set(doc_ids) - set(docs)
    if missing:
        print(
            f"WARNING: {len(missing)} requested document ID(s) have no chunks: {sorted(missing)}",
            flush=True,
        )

    print(f"\n{'document_id':<40} {'to_enrich':>10} {'total':>8} {'text_len':>10}")
    plan: dict[str, list[dict]] = {}
    for doc_id, doc in docs.items():
        to_enrich = [c for c in doc["chunks"] if not c["metadata"].get("context_prefix")]
        plan[doc_id] = to_enrich
        print(f"{doc_id:<40} {len(to_enrich):>10} {len(doc['chunks']):>8} {len(doc['text']):>10}")
    total_to_enrich = sum(len(v) for v in plan.values())
    print(f"\n{total_to_enrich} chunk(s) across {sum(1 for v in plan.values() if v)} document(s) to enrich.")

    if not args.write:
        print("\nDRY-RUN: no LLM calls made, nothing written. Pass --write to execute.", flush=True)
        await conn.close()
        return

    if total_to_enrich == 0:
        print("nothing to enrich, exiting", flush=True)
        await conn.close()
        return

    from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService

    enricher = ContextualEnricher(max_concurrency=args.concurrency)
    tenant_config = {
        "llm_steps": {"ingestion.chunk_context": {"provider": args.provider, "model": args.model}}
    }

    sparse_svc = SparseEmbeddingService()
    vector_store = MilvusVectorStore(
        MilvusConfig(
            host=s.db.milvus_host,
            port=s.db.milvus_port,
            collection_name=args.collection,
            dimensions=milvus_dimensions,
        )
    )
    await vector_store.connect()

    t0 = time.time()
    total_enriched = 0
    for doc_id, to_enrich in plan.items():
        if not to_enrich:
            continue

        # Recomputed offsets are for THIS enrichment call only -- restored to
        # the original stored values below, before anything is persisted.
        original_offsets = {c["id"]: (c["metadata"].get("start_char"), c["metadata"].get("end_char")) for c in to_enrich}
        chunk_objs = [
            SimpleNamespace(
                id=c["id"],
                document_id=c["document_id"],
                content=c["content"],
                metadata_={
                    **c["metadata"],
                    "start_char": c["reconstructed_start"],
                    "end_char": c["reconstructed_end"],
                },
            )
            for c in to_enrich
        ]
        doc_text = docs[doc_id]["text"]
        enriched_n = await enricher.enrich_chunks(
            chunk_objs,
            doc_text,
            tenant_config=tenant_config,
            settings=s,
            with_failover=args.allow_fallback,
        )
        for chunk in chunk_objs:
            _restore_original_offsets(chunk, original_offsets[chunk.id])

        yield_ratio = enriched_n / len(chunk_objs)
        print(f"{doc_id}: enriched {enriched_n}/{len(chunk_objs)} ({yield_ratio:.0%})", flush=True)
        if yield_ratio < args.min_yield:
            print(
                f"ABORT before writing '{doc_id}': yield {yield_ratio:.0%} is below "
                f"--min-yield {args.min_yield:.0%}. No chunks for this or any later "
                "document were written. Check the 'Chunk contextualization failed' "
                "warnings above for the cause, then re-run once fixed.",
                flush=True,
            )
            await conn.close()
            raise SystemExit(1)

        enriched_chunks = [c for c in chunk_objs if c.metadata_.get("context_prefix")]
        if not enriched_chunks:
            continue

        BATCH = 32
        for i in range(0, len(enriched_chunks), BATCH):
            batch = enriched_chunks[i : i + BATCH]
            texts = [c.content for c in batch]
            dense = _embed_dense(texts, s.ollama_base_url, args.embedding_model)
            sparse = sparse_svc.embed_batch(texts)
            await vector_store.upsert_chunks(
                [
                    {
                        "chunk_id": c.id,
                        "document_id": c.document_id,
                        "tenant_id": args.tenant,
                        "content": c.content[:65530],
                        "embedding": d,
                        "sparse_vector": sp or {1: 0.0001},
                        # Restore the ingestion-time dynamic metadata fields
                        # (filters/taxonomy/etc.) that a bare 6-field upsert
                        # would otherwise wipe, plus the context_prefix /
                        # original_content this enrichment pass just added.
                        **c.metadata_,
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
        total_enriched += len(enriched_chunks)

    await conn.close()
    print(
        f"done: {total_enriched}/{total_to_enrich} chunks enriched and written in {time.time()-t0:.0f}s",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
