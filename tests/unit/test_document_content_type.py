"""
Tests for ZTD-1821: _get_content_type must return correct MIME types for all
document formats that the DocumentViewer component handles.
"""

import pytest

from src.core.ingestion.domain.document import Document


def _doc(filename: str, metadata: dict | None = None) -> Document:
    return Document(
        id="doc-1",
        tenant_id="t1",
        filename=filename,
        content_hash="abc",
        storage_path="some/path",
        metadata_=metadata or {},
    )


@pytest.mark.parametrize("filename,expected", [
    ("report.pdf", "application/pdf"),
    ("README.md", "text/markdown"),
    ("README.markdown", "text/markdown"),
    ("notes.txt", "text/plain"),
    ("page.html", "text/html"),
    ("data.json", "application/json"),
    ("data.csv", "text/csv"),
    ("unknown.xyz", "text/plain"),  # default fallback
])
def test_content_type_by_extension(filename: str, expected: str | None):
    from src.api.routes.documents import _get_content_type

    doc = _doc(filename)
    assert _get_content_type(doc) == expected


def test_content_type_from_metadata_overrides_extension():
    """metadata content_type takes precedence over filename extension."""
    from src.api.routes.documents import _get_content_type

    doc = _doc("document.txt", metadata={"content_type": "application/pdf"})
    assert _get_content_type(doc) == "application/pdf"


def test_content_type_empty_metadata_falls_back_to_extension():
    from src.api.routes.documents import _get_content_type

    doc = _doc("guide.md", metadata={})
    assert _get_content_type(doc) == "text/markdown"
