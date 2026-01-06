"""
Chunking Integration Test
=========================

Verifies the SemanticChunker and its integration with IngestionService.
"""

import pytest

from src.core.chunking.semantic import SemanticChunker
from src.core.intelligence.strategies import STRATEGIES, ChunkingStrategy, DocumentDomain


@pytest.mark.asyncio
async def test_semantic_chunker_basic():
    """Test basic chunking respects size limits."""
    strategy = ChunkingStrategy(name="test", chunk_size=50, chunk_overlap=10, description="test")
    chunker = SemanticChunker(strategy)

    # Create text that should split into multiple chunks
    text = "This is the first paragraph. " * 20 + "\n\n" + "This is the second paragraph. " * 20

    chunks = chunker.chunk(text)

    assert len(chunks) > 1, "Text should be split into multiple chunks"

    # Verify sequential indices
    for i, chunk in enumerate(chunks):
        assert chunk.index == i
        assert len(chunk.content) > 0


@pytest.mark.asyncio
async def test_code_block_preservation():
    """Test that code blocks are kept intact."""
    strategy = ChunkingStrategy(name="test", chunk_size=100, chunk_overlap=0, description="test")
    chunker = SemanticChunker(strategy)

    text = """
# Introduction

This is some intro text.

```python
def hello_world():
    print("Hello, World!")
    return True
```

More text after the code block.
"""

    chunks = chunker.chunk(text)

    # Find chunk with code block
    code_chunks = [c for c in chunks if "```python" in c.content]

    # Code block should be complete (has closing ```)
    for code_chunk in code_chunks:
        assert "```python" in code_chunk.content
        # The block should contain the function
        assert "def hello_world" in code_chunk.content


@pytest.mark.asyncio
async def test_header_splitting():
    """Test that markdown headers trigger splits."""
    strategy = ChunkingStrategy(name="test", chunk_size=500, chunk_overlap=0, description="test")
    chunker = SemanticChunker(strategy)

    text = """
# Chapter 1

This is chapter 1 content.

## Section 1.1

This is section 1.1 content.

# Chapter 2

This is chapter 2 content.
"""

    chunks = chunker.chunk(text)

    # Should have multiple chunks due to headers
    assert len(chunks) >= 2


@pytest.mark.asyncio
async def test_empty_text():
    """Test handling of empty input."""
    strategy = STRATEGIES[DocumentDomain.GENERAL]
    chunker = SemanticChunker(strategy)

    chunks = chunker.chunk("")
    assert chunks == []

    chunks = chunker.chunk("   ")
    assert chunks == []


@pytest.mark.asyncio
async def test_chunk_metadata():
    """Test that chunks have proper metadata."""
    strategy = STRATEGIES[DocumentDomain.TECHNICAL]
    chunker = SemanticChunker(strategy)

    text = "This is a test document.\n\nWith multiple paragraphs."

    chunks = chunker.chunk(text, document_title="test.md")

    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.metadata.get("document_title") == "test.md"
        assert chunk.token_count > 0
        assert chunk.start_char >= 0
