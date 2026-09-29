from src.core.generation.application.intelligence.strategies import ChunkingStrategy
from src.core.ingestion.application.chunking.semantic import SemanticChunker

TEXT = (
    "## Known issues\n\n| Upload fails silently | Check the admin console |\n\n"
    "## Reference\n\n### Endpoints Summary\n\n"
    "| Method | Path |\n| PUT | /services/storage/admin/quota/config/accounts/{accountId} |\n"
)


def _chunker(overlap: int) -> SemanticChunker:
    return SemanticChunker(ChunkingStrategy(name="t", chunk_size=40, chunk_overlap=overlap, description="t"))


def test_chunk_opening_a_header_section_gets_no_overlap():
    chunks = _chunker(10).chunk(TEXT)
    endpoints = next(c for c in chunks if "Endpoints Summary" in c.content)
    assert endpoints.content.startswith("### Endpoints Summary")
    assert "Upload fails silently" not in endpoints.content


def test_chunk_continuing_a_section_keeps_overlap():
    text = "## Guide\n\n" + "\n\n".join(f"Paragraph {n} explains step {n} of the setup." for n in range(12))
    chunks = _chunker(5).chunk(text)
    assert len(chunks) > 1
    # the second chunk is led by the tail of the first, not by its own paragraph
    assert not chunks[1].content.startswith(("#", "Paragraph"))
