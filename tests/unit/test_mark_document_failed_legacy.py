"""A failed reprocess must not hide a document that still serves content.

Legacy documents (ingested before generations) have active_generation_id NULL but
serve their NULL-generation chunks; the Celery failure handler marked them FAILED,
which removed them from retrieval with no error recorded."""

from types import SimpleNamespace

import pytest

from src.core.state.machine import DocumentStatus
from src.workers.tasks import _serves_published_content


@pytest.mark.parametrize(
    ("active", "status", "legacy", "keep"),
    [
        ("gen-1", DocumentStatus.READY, False, True),  # published generation
        ("gen-1", DocumentStatus.FAILED, False, True),
        (None, DocumentStatus.READY, True, True),  # legacy doc serving NULL-gen chunks
        (None, DocumentStatus.READY, False, False),  # nothing served
        (None, DocumentStatus.FAILED, True, False),  # already hidden: stays FAILED
        (None, DocumentStatus.EXTRACTING, False, False),  # first ingestion failing
    ],
)
def test_serves_published_content(active, status, legacy, keep):
    doc = SimpleNamespace(active_generation_id=active, status=status)
    assert _serves_published_content(doc, legacy) is keep


def test_failure_handler_records_the_error_and_checks_legacy_chunks():
    import inspect

    from src.workers import tasks

    source = inspect.getsource(tasks._mark_document_failed)
    assert "_serves_published_content(document, has_legacy_chunks)" in source
    assert "_Chunk.generation_id.is_(None)" in source
    assert "document.error_message =" in source
