"""Small, in-memory corpus for the locally supported parser stack."""

import base64
import io
import time

import pytest

from src.core.ingestion.infrastructure.extraction.local.html_extractor import HtmlExtractor
from src.core.ingestion.infrastructure.extraction.local.pymupdf_extractor import (
    HAS_PYMUPDF,
    PyMuPDFExtractor,
)
from src.core.ingestion.infrastructure.extraction.local.unstructured_extractor import (
    HAS_UNSTRUCTURED,
    UnstructuredExtractor,
)

# 64x64 HEVC sample from the upstream libheif fuzz corpus. It is intentionally
# embedded so the parser corpus is deterministic and never performs I/O.
HEIF_CORPUS = base64.b64decode(
    "AAAAEGZ0eXBtaWYzaGVpYwAAAOptaW5pCAg/fiBuANYBA3AAAAAAAAAAAAAe8AD8/fj4AAAPA2AAAQAYQAEMAf//A3AAAAMAkAAAAwAAAwAeugJAYQABACpCAQEDcAAAAwCQAAADAAADAB6gIIEFlurkprm4CGgwIAAAAwMgAAADACFiAAEABkQBwXPAiQAAAGgoAa8TgPUrAhGDczL1mz4HCRRzxqbGjnnUrr1cLTO799zRz6nw0QjRMp+4I2Da10D3ghQEMvB53CWoI0S3qXIb99YsvLFaQ9ZLHxsJsZ9SxlvNJ5EgD4Y4miuaKu3bxPGXDHirp/9TzA=="
)


@pytest.mark.asyncio
async def test_pdf_corpus_extracts_text():
    fitz = pytest.importorskip("fitz")
    if not HAS_PYMUPDF:
        pytest.skip("pymupdf4llm is not installed")

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Amber PDF corpus")

    result = await PyMuPDFExtractor().extract(document.tobytes(), "application/pdf")

    assert "Amber PDF corpus" in result.content


@pytest.mark.asyncio
async def test_docx_corpus_extracts_text():
    docx = pytest.importorskip("docx")
    if not HAS_UNSTRUCTURED:
        pytest.skip("unstructured is not installed")

    document = docx.Document()
    document.add_paragraph("Amber DOCX corpus")
    document_bytes = io.BytesIO()
    document.save(document_bytes)

    result = await UnstructuredExtractor().extract(
        document_bytes.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert "Amber DOCX corpus" in result.content


@pytest.mark.asyncio
async def test_html_corpus_extracts_visible_text():
    pytest.importorskip("bs4")

    result = await HtmlExtractor().extract(
        b"<html><body><h1>Amber HTML corpus</h1><script>ignored()</script></body></html>",
        "text/html",
    )

    assert result.content == "Amber HTML corpus"


def test_heif_corpus_decodes_with_the_local_parser():
    pi_heif = pytest.importorskip("pi_heif")
    decoded = pi_heif.open_heif(HEIF_CORPUS)

    assert decoded.size == (64, 64)
    assert decoded.mode == "RGB"
    assert decoded.to_pillow().size == (64, 64)


def test_malformed_image_fails_locally_without_ocr_or_network():
    pi_heif = pytest.importorskip("pi_heif")

    started = time.monotonic()
    with pytest.raises(ValueError):
        pi_heif.open_heif(b"not an image")

    assert time.monotonic() - started < 1
