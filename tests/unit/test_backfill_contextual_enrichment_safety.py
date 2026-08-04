"""
Regression tests for Issue #98 (backfill_contextual_enrichment.py safety).

The script is invoked as a standalone CLI, but its critical safety logic
(doc-id parsing, model-registry validation, per-document text
reconstruction, and the transient-offset restore that must run before any
persistence) is factored into pure/isolated functions so it can be unit
tested without a live Postgres/Milvus/LLM connection.
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# The script lives outside any package (scripts/), so import it by path
# rather than by dotted module name.
_SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "backfill_contextual_enrichment.py"
_spec = importlib.util.spec_from_file_location("backfill_contextual_enrichment", _SCRIPT_PATH)
backfill = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = backfill
_spec.loader.exec_module(backfill)


# ---------------------------------------------------------------------------
# _load_doc_ids
# ---------------------------------------------------------------------------


def test_load_doc_ids_skips_blank_lines_and_comments(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("doc_a\n\n# a comment\ndoc_b  # trailing comment\n   \ndoc_c\n")

    assert backfill._load_doc_ids(str(f)) == ["doc_a", "doc_b", "doc_c"]


# ---------------------------------------------------------------------------
# _validate_model
# ---------------------------------------------------------------------------


def test_validate_model_accepts_known_provider_model():
    # gpt-4o-mini/openai is a real registry entry.
    assert backfill._validate_model("openai", "gpt-4o-mini") is None


def test_validate_model_rejects_unknown_model_and_lists_alternatives():
    msg = backfill._validate_model("openai", "definitely-not-a-real-model")
    assert msg is not None
    assert "definitely-not-a-real-model" in msg
    assert "openai" in msg
    assert "gpt-4o-mini" in msg  # a real alternative is surfaced


def test_validate_model_rejects_unknown_provider():
    msg = backfill._validate_model("not-a-real-provider", "whatever")
    assert msg is not None
    assert "not-a-real-provider" in msg


# ---------------------------------------------------------------------------
# _reconstruct_documents
# ---------------------------------------------------------------------------


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _query, *_args):
        return self._rows


def _row(id_, document_id, content, metadata, index):
    return {"id": id_, "document_id": document_id, "content": content, "metadata": metadata, "index": index}


@pytest.mark.asyncio
async def test_reconstruct_documents_uses_original_content_not_prefixed_content():
    """A chunk that's already enriched must contribute its PRE-prefix text
    to the reconstruction, not the prefixed content -- otherwise a
    previously generated context prefix leaks into the prompt used to
    generate a sibling chunk's context."""
    rows = [
        _row("c1", "d1", "Some context.\n\nReal body one.", {"original_content": "Real body one.", "context_prefix": "Some context."}, 0),
        _row("c2", "d1", "Real body two.", {}, 1),
    ]
    conn = _FakeConn(rows)

    docs = await backfill._reconstruct_documents(conn, "tenant-1", ["d1"])

    assert docs["d1"]["text"] == "Real body one.\n\nReal body two."


@pytest.mark.asyncio
async def test_reconstruct_documents_computes_correct_offsets_per_chunk():
    rows = [
        _row("c1", "d1", "First.", {}, 0),
        _row("c2", "d1", "Second.", {}, 1),
    ]
    conn = _FakeConn(rows)

    docs = await backfill._reconstruct_documents(conn, "tenant-1", ["d1"])
    text = docs["d1"]["text"]
    chunks = docs["d1"]["chunks"]

    assert text == "First.\n\nSecond."
    c1, c2 = chunks
    assert text[c1["reconstructed_start"] : c1["reconstructed_end"]] == "First."
    assert text[c2["reconstructed_start"] : c2["reconstructed_end"]] == "Second."


@pytest.mark.asyncio
async def test_reconstruct_documents_groups_by_document_id():
    rows = [
        _row("c1", "d1", "D1 chunk.", {}, 0),
        _row("c2", "d2", "D2 chunk.", {}, 0),
    ]
    conn = _FakeConn(rows)

    docs = await backfill._reconstruct_documents(conn, "tenant-1", ["d1", "d2"])

    assert set(docs) == {"d1", "d2"}
    assert docs["d1"]["text"] == "D1 chunk."
    assert docs["d2"]["text"] == "D2 chunk."


@pytest.mark.asyncio
async def test_reconstruct_documents_parses_json_string_metadata():
    """asyncpg may return jsonb as a raw JSON string rather than a parsed
    dict depending on codec setup -- both forms must work."""
    rows = [_row("c1", "d1", "Body.", '{"original_content": "Pristine."}', 0)]
    conn = _FakeConn(rows)

    docs = await backfill._reconstruct_documents(conn, "tenant-1", ["d1"])

    assert docs["d1"]["text"] == "Pristine."


# ---------------------------------------------------------------------------
# _restore_original_offsets
# ---------------------------------------------------------------------------


def test_restore_original_offsets_restores_present_values():
    """The reconstructed offsets used during enrichment must never survive
    into what gets persisted -- restoring a present original value."""
    chunk = SimpleNamespace(metadata_={"start_char": 9999, "end_char": 10050, "context_prefix": "ctx"})

    backfill._restore_original_offsets(chunk, (10, 20))

    assert chunk.metadata_["start_char"] == 10
    assert chunk.metadata_["end_char"] == 20


def test_restore_original_offsets_removes_keys_that_were_absent():
    """If the chunk never had start_char/end_char in the first place (no
    original value to restore), the temporary reconstruction offsets must
    be removed entirely, not left in place as fabricated data."""
    chunk = SimpleNamespace(metadata_={"start_char": 9999, "end_char": 10050, "context_prefix": "ctx"})

    backfill._restore_original_offsets(chunk, (None, None))

    assert "start_char" not in chunk.metadata_
    assert "end_char" not in chunk.metadata_


def test_restore_original_offsets_does_not_touch_other_metadata():
    chunk = SimpleNamespace(
        metadata_={"start_char": 1, "end_char": 2, "context_prefix": "ctx", "extractor": "pdf"}
    )

    backfill._restore_original_offsets(chunk, (5, 6))

    assert chunk.metadata_["extractor"] == "pdf"
    assert chunk.metadata_["context_prefix"] == "ctx"


# ---------------------------------------------------------------------------
# _probe_collection
# ---------------------------------------------------------------------------


class _FakeField:
    def __init__(self, name, params):
        self.name = name
        self.params = params


class _FakeSchema:
    def __init__(self, fields):
        self.fields = fields


class _FakeCollection:
    def __init__(self, dim):
        self.schema = _FakeSchema([_FakeField("vector", {"dim": dim}), _FakeField("chunk_id", {})])


def _fake_milvus(existing_collections: dict[str, int]):
    """existing_collections: {collection_name: vector_dim}"""
    return {
        "utility": SimpleNamespace(has_collection=lambda name: name in existing_collections),
        "Collection": lambda name: _FakeCollection(existing_collections[name]),
    }


def test_probe_collection_reports_missing_collection():
    """Regression test for issue #98 (B3): a nonexistent collection must be
    reported as missing, not silently treated as something that will be
    auto-created -- the caller aborts on False rather than letting
    MilvusVectorStore.connect() create an empty collection under a typo'd
    name (a phantom write that leaves the real collection untouched)."""
    milvus = _fake_milvus({})

    exists, dimensions = backfill._probe_collection(milvus, "does_not_exist", "vector")

    assert exists is False
    assert dimensions is None


def test_probe_collection_reads_real_dimension_of_existing_collection():
    """The dimension must come from the LIVE collection schema, not a
    hardcoded default -- so the embedding-dimension parity guard in
    upsert_chunks checks against reality."""
    milvus = _fake_milvus({"amber_default": 1536})

    exists, dimensions = backfill._probe_collection(milvus, "amber_default", "vector")

    assert exists is True
    assert dimensions == 1536
