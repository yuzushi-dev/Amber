"""
Regression tests for issue #109: `DeleteDocumentUseCase` orphan-entity cleanup.

The original `cypher` query in `delete_document`'s Neo4j cleanup grouped by
``WITH d, c, collect(DISTINCT e) AS entities`` -- since `c` (the chunk) was a
non-aggregated identifier in that WITH, Cypher's implicit grouping produced
one row PER CHUNK instead of one row per document. When an entity was
mentioned by two-or-more chunks of the SAME document, the orphan check
(`NOT (entity)<-[:MENTIONS]-()`) evaluated on one chunk's row could still see
a live MENTIONS edge from a sibling chunk of the same document not yet
processed within that row, so the entity's DETACH DELETE was skipped -- even
though, once ALL of the document's chunks are gone, the entity has zero
mentions and should be removed.

These tests cover two angles:
  1. A structural check that the query text uses document-scoped grouping
     (`collect(DISTINCT c) AS chunks`, `FOREACH ... DETACH DELETE ch`) and no
     longer contains the buggy `WITH d, c, collect(DISTINCT e)` grouping.
  2. A semantic check, using an in-memory fake graph that models chunks /
     entities / MENTIONS edges and applies the same document-scoped cleanup
     the fixed query performs, verifying: an entity mentioned only by chunks
     of the deleted document is removed, an entity also mentioned by a chunk
     of a different (non-deleted) document is kept, and an entity mentioned
     only via a "property-linked" chunk (no HAS_CHUNK edge -- cleaned up by
     the separate `orphan_chunk_cypher` pass) is still caught by the
     tenant-wide defensive sweep kept for that purpose.
"""

from types import SimpleNamespace

import pytest

from src.core.ingestion.application.use_cases_documents import (
    DeleteDocumentRequest,
    DeleteDocumentUseCase,
)


class FakeResult:
    def __init__(self, document):
        self._document = document

    def scalars(self):
        return self

    def first(self):
        return self._document


class FakeSession:
    """Minimal AsyncSession stand-in: one document row, no-op delete/commit."""

    def __init__(self, document):
        self._document = document

    async def execute(self, _query):
        return FakeResult(self._document)

    async def delete(self, _document):
        return None

    async def commit(self):
        return None


class FakeVectorStore:
    async def delete_by_document(self, _document_id, _tenant_id):
        return None

    async def disconnect(self):
        return None


class FakeStorage:
    def delete_file(self, _path):
        return None


class FakeGraph:
    """
    In-memory graph model that implements the *intended* (fixed) semantics of
    each cypher block in `delete_document`, dispatched by distinguishing
    substrings of the literal query text used in the production code. This
    lets the test assert on real orphan-cleanup outcomes rather than only on
    query text.

    Model:
      chunks:   chunk_id -> {tenant_id, document_id, has_chunk, mentions: set[entity_id]}
      entities: entity_id -> tenant_id
      deleted_chunks / deleted_entities / deleted_documents: sets of ids
    """

    def __init__(self, chunks, entities):
        self.chunks = chunks
        self.entities = entities
        self.deleted_chunks: set[str] = set()
        self.deleted_entities: set[str] = set()
        self.deleted_documents: set[str] = set()
        self.reads: list[tuple[str, dict]] = []
        self.writes: list[tuple[str, dict]] = []

    def _live_chunks(self):
        return {cid: c for cid, c in self.chunks.items() if cid not in self.deleted_chunks}

    def _entity_has_live_mention(self, entity_id: str) -> bool:
        return any(entity_id in c["mentions"] for c in self._live_chunks().values())

    async def execute_read(self, query, parameters=None):
        self.reads.append((query, parameters))
        if "RETURN collect(DISTINCT c.id) AS ids" in query:
            # Community collection is out of scope for this test; no communities modeled.
            return [{"ids": []}]
        raise AssertionError(f"Unexpected read query in test: {query}")

    async def execute_write(self, query, parameters=None):
        self.writes.append((query, parameters))
        parameters = parameters or {}

        if "FOREACH (ch IN chunks | DETACH DELETE ch)" in query:
            # Primary document-scoped cleanup (the fixed query).
            document_id = parameters["document_id"]
            tenant_id = parameters["tenant_id"]
            matched = [
                cid
                for cid, c in self._live_chunks().items()
                if c["document_id"] == document_id
                and c["tenant_id"] == tenant_id
                and c["has_chunk"]
            ]
            mentioned_entities = {e for cid in matched for e in self.chunks[cid]["mentions"]}
            self.deleted_chunks.update(matched)
            self.deleted_documents.add(document_id)
            for entity_id in mentioned_entities:
                if not self._entity_has_live_mention(entity_id):
                    self.deleted_entities.add(entity_id)
            return []

        if "MATCH (c:Chunk {document_id: $document_id" in query:
            # orphan_chunk_cypher: property-linked chunks (no HAS_CHUNK edge).
            document_id = parameters["document_id"]
            tenant_id = parameters["tenant_id"]
            matched = [
                cid
                for cid, c in self._live_chunks().items()
                if c["document_id"] == document_id and c["tenant_id"] == tenant_id
            ]
            self.deleted_chunks.update(matched)
            return []

        if "MATCH (c:Community" in query:
            # Community cleanup: no communities modeled, no-op.
            return []

        if "MATCH (e:Entity {tenant_id: $tenant_id})" in query and "NOT (:Chunk)" in query:
            # Tenant-wide defensive orphan-entity sweep.
            tenant_id = parameters["tenant_id"]
            for entity_id, entity_tenant in self.entities.items():
                if entity_tenant != tenant_id or entity_id in self.deleted_entities:
                    continue
                if not self._entity_has_live_mention(entity_id):
                    self.deleted_entities.add(entity_id)
            return []

        if "SET c.is_stale = true" in query:
            return [{"marked": 0}]

        raise AssertionError(f"Unexpected write query in test: {query}")


def _make_use_case(graph: FakeGraph, document) -> DeleteDocumentUseCase:
    return DeleteDocumentUseCase(
        session=FakeSession(document),
        storage=FakeStorage(),
        graph_client=graph,
        vector_store_factory=lambda _tenant_id: FakeVectorStore(),
    )


@pytest.mark.unit
async def test_primary_cypher_groups_by_document_not_by_chunk():
    """Structural guard: the buggy per-chunk grouping must never come back."""
    document = SimpleNamespace(tenant_id="tenant-1", storage_path="tenant-1/doc-1/file.txt")
    graph = FakeGraph(chunks={}, entities={})
    use_case = _make_use_case(graph, document)

    await use_case.execute(DeleteDocumentRequest(document_id="doc-1", tenant_id="tenant-1"))

    primary_query = next(q for q, _ in graph.writes if "FOREACH (ch IN chunks" in q)
    assert "collect(DISTINCT c) AS chunks" in primary_query
    assert "collect(DISTINCT e) AS entities" in primary_query
    assert "WITH d, c, collect(DISTINCT e)" not in primary_query


@pytest.mark.unit
async def test_entity_mentioned_by_two_chunks_of_same_deleted_document_is_removed():
    """Issue #109 scenario: entity mentioned by 2+ chunks of the SAME document."""
    document = SimpleNamespace(tenant_id="tenant-1", storage_path="tenant-1/doc-1/file.txt")
    chunks = {
        "chunk-1": {
            "tenant_id": "tenant-1",
            "document_id": "doc-1",
            "has_chunk": True,
            "mentions": {"entity-shared"},
        },
        "chunk-2": {
            "tenant_id": "tenant-1",
            "document_id": "doc-1",
            "has_chunk": True,
            "mentions": {"entity-shared"},
        },
    }
    entities = {"entity-shared": "tenant-1"}
    graph = FakeGraph(chunks=chunks, entities=entities)
    use_case = _make_use_case(graph, document)

    await use_case.execute(DeleteDocumentRequest(document_id="doc-1", tenant_id="tenant-1"))

    assert "chunk-1" in graph.deleted_chunks
    assert "chunk-2" in graph.deleted_chunks
    assert "entity-shared" in graph.deleted_entities


@pytest.mark.unit
async def test_entity_mentioned_by_another_documents_chunk_is_kept():
    """An entity still mentioned by a chunk of a DIFFERENT, non-deleted document survives."""
    document = SimpleNamespace(tenant_id="tenant-1", storage_path="tenant-1/doc-1/file.txt")
    chunks = {
        "chunk-1": {
            "tenant_id": "tenant-1",
            "document_id": "doc-1",
            "has_chunk": True,
            "mentions": {"entity-cross-doc"},
        },
        "chunk-other-doc": {
            "tenant_id": "tenant-1",
            "document_id": "doc-2",
            "has_chunk": True,
            "mentions": {"entity-cross-doc"},
        },
    }
    entities = {"entity-cross-doc": "tenant-1"}
    graph = FakeGraph(chunks=chunks, entities=entities)
    use_case = _make_use_case(graph, document)

    await use_case.execute(DeleteDocumentRequest(document_id="doc-1", tenant_id="tenant-1"))

    assert "chunk-1" in graph.deleted_chunks
    assert "chunk-other-doc" not in graph.deleted_chunks
    assert "entity-cross-doc" not in graph.deleted_entities


@pytest.mark.unit
async def test_tenant_wide_sweep_catches_entity_orphaned_via_property_linked_chunk():
    """
    Entity mentioned only by a chunk linked to the document by the
    `document_id` property (no HAS_CHUNK edge) is not reachable by the
    primary document-scoped query's entity collection; it is cleaned up by
    the property-linked chunk deletion pass plus the tenant-wide defensive
    sweep -- the reason that sweep is kept rather than removed.
    """
    document = SimpleNamespace(tenant_id="tenant-1", storage_path="tenant-1/doc-1/file.txt")
    chunks = {
        "chunk-property-only": {
            "tenant_id": "tenant-1",
            "document_id": "doc-1",
            "has_chunk": False,
            "mentions": {"entity-property-only"},
        },
    }
    entities = {"entity-property-only": "tenant-1"}
    graph = FakeGraph(chunks=chunks, entities=entities)
    use_case = _make_use_case(graph, document)

    await use_case.execute(DeleteDocumentRequest(document_id="doc-1", tenant_id="tenant-1"))

    assert "chunk-property-only" in graph.deleted_chunks
    assert "entity-property-only" in graph.deleted_entities
