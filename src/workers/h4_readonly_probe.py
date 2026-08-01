"""Fail-closed, read-only readiness probe for H4 production workers."""

from __future__ import annotations

import asyncio
import sys
from typing import Any


class ProbeFailure(RuntimeError):
    """Raised when a required H4 worker invariant is not proven."""


def validate_provider_settings(settings: Any) -> None:
    """Require the live app role and the selected Ollama Cloud configuration."""
    if not settings.db.app_database_url:
        raise ProbeFailure("application database role is not configured")
    if settings.default_llm_provider != "ollama_cloud":
        raise ProbeFailure("default LLM provider is not ollama_cloud")
    if not settings.default_llm_model:
        raise ProbeFailure("default LLM model is not configured")
    if not settings.ollama_cloud_api_keys:
        raise ProbeFailure("Ollama Cloud key pool is empty")


def validate_role_evidence(
    *,
    superuser: bool,
    bypass_rls: bool,
    owns_documents: bool,
    rls_enabled: bool = True,
    rls_forced: bool = True,
) -> None:
    """Reject a database role that can bypass the documents RLS boundary."""
    if superuser or bypass_rls or owns_documents or not rls_enabled or not rls_forced:
        raise ProbeFailure("application database role does not enforce document RLS")


async def probe_database(settings: Any) -> None:
    """Read database role metadata in an explicitly read-only transaction."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.db.app_database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            result = await connection.execute(
                text(
                    """
                    SELECT
                        role.rolsuper,
                        role.rolbypassrls,
                        pg_get_userbyid(document.relowner) = current_user AS owns_documents,
                        document.relrowsecurity,
                        document.relforcerowsecurity
                    FROM pg_roles AS role
                    JOIN pg_class AS document ON document.relname = 'documents'
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = document.relnamespace
                    WHERE role.rolname = current_user
                      AND namespace.nspname = current_schema()
                    """
                )
            )
            row = result.one()
            validate_role_evidence(
                superuser=bool(row.rolsuper),
                bypass_rls=bool(row.rolbypassrls),
                owns_documents=bool(row.owns_documents),
                rls_enabled=bool(row.relrowsecurity),
                rls_forced=bool(row.relforcerowsecurity),
            )
            await connection.rollback()
    finally:
        await engine.dispose()


async def probe_runtime(settings: Any) -> None:
    """Exercise provider construction, SPLADE, and FlashRank without network writes."""
    from src.core.generation.infrastructure.providers.factory import ProviderFactory
    from src.core.generation.infrastructure.providers.local import FlashRankReranker
    from src.core.retrieval.application.sparse_embeddings_service import (
        SparseEmbeddingService,
    )
    from src.shared.h4_ml_runtime import validated_h4_runtime_root

    runtime_root = validated_h4_runtime_root()
    if runtime_root is None:
        raise ProbeFailure("validated H4 runtime is not enabled")

    factory = ProviderFactory(
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        ollama_cloud_base_url=settings.ollama_cloud_base_url,
        ollama_cloud_api_keys=settings.ollama_cloud_api_keys,
        llm_fallback_enabled=settings.llm_fallback_enabled,
    )
    provider = factory.get_llm_provider(
        provider_name="ollama_cloud",
        model=settings.default_llm_model,
        with_failover=False,
    )
    if provider is None:
        raise ProbeFailure("Ollama Cloud provider construction failed")

    sparse_terms = SparseEmbeddingService().embed_sparse("H4 read only readiness probe")
    if not sparse_terms:
        raise ProbeFailure("SPLADE returned no sparse terms")

    reranked = await FlashRankReranker().rerank(
        "H4 read only readiness probe",
        ["validated immutable runtime", "unrelated text"],
        top_k=2,
    )
    if len(reranked.results) != 2:
        raise ProbeFailure("FlashRank did not return both probe documents")


async def run_probe() -> None:
    """Run every worker readiness gate without mutating application data."""
    from src.api.config import settings

    validate_provider_settings(settings)
    await probe_database(settings)
    await probe_runtime(settings)


def main() -> int:
    try:
        asyncio.run(run_probe())
    except Exception as exc:
        print(f"H4 worker read-only probe: FAIL ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("H4 worker read-only probe: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
