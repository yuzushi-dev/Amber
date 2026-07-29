import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.core.retrieval.application.embeddings_service import EmbeddingService
from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService
from src.core.retrieval.domain.ports.vector_store_port import VectorStorePort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommunityEmbeddingSelection:
    """Communities requiring an embedding write and those already current."""

    communities: list[dict[str, Any]]
    skipped_current: int


@dataclass(frozen=True)
class CommunityEmbeddingSyncStats:
    """Observable result of one community embedding synchronization pass."""

    ready: int
    candidates: int
    skipped_current: int
    embedded: int
    batches: int
    cancelled: bool = False


class CommunityEmbeddingService:
    """
    Handles embedding and storage of community summaries in the vector store.
    """

    FIELD_COMMUNITY_ID = "community_id"
    FIELD_TENANT_ID = "tenant_id"
    FIELD_LEVEL = "level"
    FIELD_TITLE = "title"
    FIELD_SUMMARY = "summary"
    FIELD_VECTOR = "vector"
    MARKER_VERSION = "community-embedding-v1"

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStorePort,
        sparse_embedding_service: SparseEmbeddingService | None = None,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.sparse_embedding_service = sparse_embedding_service

    @classmethod
    def embedding_marker(
        cls,
        community: dict[str, Any],
        *,
        provider: str,
        model: str,
        dimensions: int,
    ) -> str:
        """Return a versioned marker for the exact vector representation.

        The marker intentionally includes the embedding identity as a model or
        dimension change makes an otherwise identical summary stale.
        """
        content = {
            "dimensions": dimensions,
            "marker_version": cls.MARKER_VERSION,
            "model": model,
            "provider": provider,
            "summary": community.get("summary") or "",
            "title": community.get("title") or "",
        }
        serialized = json.dumps(content, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return f"{cls.MARKER_VERSION}:{hashlib.sha256(serialized.encode()).hexdigest()}"

    def select_stale_communities(
        self,
        communities: list[dict[str, Any]],
        *,
        provider: str,
        model: str,
        dimensions: int,
        force_full_resync: bool = False,
        force_full_resync_id: str | None = None,
    ) -> CommunityEmbeddingSelection:
        """Select only missing or stale community vectors from ready nodes."""
        if force_full_resync and not force_full_resync_id:
            raise ValueError("A force full resync requires a stable resync ID")

        stale: list[dict[str, Any]] = []
        skipped_current = 0
        for community in communities:
            marker = self.embedding_marker(
                community, provider=provider, model=model, dimensions=dimensions
            )
            marker_is_current = community.get("embedding_content_hash") == marker
            full_resync_acknowledged = (
                not force_full_resync
                or community.get("embedding_resync_run_id") == force_full_resync_id
            )
            if marker_is_current and full_resync_acknowledged:
                skipped_current += 1
                continue
            stale.append({**community, "_embedding_content_hash": marker})
        return CommunityEmbeddingSelection(communities=stale, skipped_current=skipped_current)

    async def sync_stale_communities(
        self,
        communities: list[dict[str, Any]],
        *,
        graph_client: Any,
        provider: str,
        model: str,
        dimensions: int,
        force_full_resync: bool = False,
        force_full_resync_id: str | None = None,
        batch_size: int = 200,
        concurrency: int = 5,
        should_cancel: Callable[[], bool] | None = None,
    ) -> CommunityEmbeddingSyncStats:
        """Embed stale communities and mark them current after each successful upsert.

        Persisting the marker only after its batch has reached the vector store
        makes retries naturally resume from the last acknowledged batch.
        """
        selection = self.select_stale_communities(
            communities,
            provider=provider,
            model=model,
            dimensions=dimensions,
            force_full_resync=force_full_resync,
            force_full_resync_id=force_full_resync_id,
        )
        candidates = selection.communities
        if not candidates:
            return CommunityEmbeddingSyncStats(
                ready=len(communities),
                candidates=0,
                skipped_current=selection.skipped_current,
                embedded=0,
                batches=0,
            )

        semaphore = asyncio.Semaphore(concurrency)

        async def embed_community(community: dict[str, Any]) -> dict[str, Any]:
            text = f"{community.get('title') or ''}: {community.get('summary') or ''}"
            async with semaphore:
                dense = await self.embedding_service.embed_single(text)

            payload = {
                "chunk_id": community["id"],
                "document_id": community["id"],
                "tenant_id": community["tenant_id"],
                "content": community.get("summary") or "",
                "embedding": dense,
                "title": community.get("title") or "",
                "level": community.get("level"),
            }
            if self.sparse_embedding_service:
                try:
                    sparse = self.sparse_embedding_service.embed_sparse(text)
                    if sparse:
                        payload["sparse_vector"] = sparse
                except Exception as exc:
                    logger.warning(
                        "Sparse embedding failed for community %s: %s", community["id"], exc
                    )
            return payload

        embedded = 0
        batches = 0
        for offset in range(0, len(candidates), batch_size):
            if should_cancel and should_cancel():
                return CommunityEmbeddingSyncStats(
                    ready=len(communities),
                    candidates=len(candidates),
                    skipped_current=selection.skipped_current,
                    embedded=embedded,
                    batches=batches,
                    cancelled=True,
                )

            batch = candidates[offset : offset + batch_size]
            payloads = await asyncio.gather(*(embed_community(community) for community in batch))
            await self.vector_store.upsert_chunks(list(payloads))
            await self._mark_batch_embedded(
                graph_client,
                batch,
                provider=provider,
                model=model,
                dimensions=dimensions,
                force_full_resync_id=force_full_resync_id,
            )
            embedded += len(batch)
            batches += 1
            logger.info(
                "Community embedding batch %s complete (%s/%s vectors)",
                batches,
                embedded,
                len(candidates),
            )

        return CommunityEmbeddingSyncStats(
            ready=len(communities),
            candidates=len(candidates),
            skipped_current=selection.skipped_current,
            embedded=embedded,
            batches=batches,
        )

    async def _mark_batch_embedded(
        self,
        graph_client: Any,
        communities: list[dict[str, Any]],
        *,
        provider: str,
        model: str,
        dimensions: int,
        force_full_resync_id: str | None,
    ) -> None:
        """Acknowledge vector writes in Neo4j after a successful batch upsert."""
        query = """
        UNWIND $communities AS community
        MATCH (c:Community {id: community.id, tenant_id: community.tenant_id})
        SET c.embedding_content_hash = community.embedding_content_hash,
            c.embedding_marker_version = $marker_version,
            c.embedding_provider = $provider,
            c.embedding_model = $model,
            c.embedding_dimensions = $dimensions,
            c.embedding_resync_run_id = coalesce($force_full_resync_id, c.embedding_resync_run_id),
            c.embedding_updated_at = datetime()
        """
        marked = [
            {
                "id": community["id"],
                "tenant_id": community["tenant_id"],
                "embedding_content_hash": community["_embedding_content_hash"],
            }
            for community in communities
        ]
        await graph_client.execute_write(
            query,
            {
                "communities": marked,
                "marker_version": self.MARKER_VERSION,
                "provider": provider,
                "model": model,
                "dimensions": dimensions,
                "force_full_resync_id": force_full_resync_id,
            },
        )
