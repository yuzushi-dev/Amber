"""Decision table for keeping a document READY after a failed (re)processing."""

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
