"""
Semantic Chunker
================

Structure-aware text chunking that respects document hierarchy.
"""

import logging
import re
from dataclasses import dataclass, field

try:
    import tiktoken

    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

from src.core.generation.application.intelligence.strategies import ChunkingStrategy
from src.core.ingestion.application.chunking.quality import ChunkQualityScorer

logger = logging.getLogger(__name__)


@dataclass
class ChunkData:
    """Represents a single chunk with metadata."""

    content: str
    index: int
    start_char: int
    end_char: int
    token_count: int
    metadata: dict = field(default_factory=dict)


class SemanticChunker:
    """
    Hierarchical semantic chunker that respects document structure.

    Split order:
    1. Markdown headers (# ## ###)
    2. Code blocks (```)
    3. Double newlines (paragraphs)
    4. Sentences
    """

    # Regex patterns
    HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    PARAGRAPH_PATTERN = re.compile(r"\n\n+")
    SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")

    # ponytail: nomic-embed-text (v1) embed ctx ceiling = 2048 nomic tokens
    # (~1.1-1.3x cl100k). Oversized chunks (big code blocks/tables) exceed it -> embed 400
    # -> ingestion FAILED. Hard-split contiguously (no data loss). Raise to ~7000 if
    # upgraded to nomic v1.5 (ctx 8192).
    EMBED_TOKEN_CAP = 1200  # cl100k tokens; ~1560 nomic at 1.3x -> safe margin under 2048

    def __init__(self, strategy: ChunkingStrategy, encoding_name: str = "cl100k_base"):
        """
        Initialize chunker with strategy parameters.

        Args:
            strategy: ChunkingStrategy with chunk_size and chunk_overlap.
            encoding_name: Tiktoken encoding (cl100k_base for GPT-4/3.5).
        """
        self.chunk_size = strategy.chunk_size
        self.chunk_overlap = strategy.chunk_overlap
        self.quality_scorer = ChunkQualityScorer()

        if HAS_TIKTOKEN:
            try:
                self.encoder = tiktoken.get_encoding(encoding_name)
            except Exception as e:
                logger.warning(f"Failed to initialize tiktoken ({e}). Using word-based estimation.")
                self.encoder = None
        else:
            self.encoder = None
            logger.warning("tiktoken not available, using word-based estimation")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if self.encoder:
            return len(self.encoder.encode(text))
        # Fallback: rough word-based estimate
        return len(text.split())

    def chunk(
        self, text: str, document_title: str | None = None, metadata: dict | None = None
    ) -> list[ChunkData]:
        """
        Split text into semantic chunks.

        Args:
            text: Full document text.
            document_title: Optional title for context enrichment.
            metadata: Optional metadata from extraction (e.g. code definitions).

        Returns:
            List of ChunkData objects.
        """
        if not text or not text.strip():
            return []

        # [NEW] Check for code definitions
        if metadata and metadata.get("definitions"):
            return self._split_from_definitions(text, metadata["definitions"], document_title)

        # Step 1: Extract and protect code blocks
        code_blocks = {}
        protected_text = text
        for i, match in enumerate(self.CODE_BLOCK_PATTERN.finditer(text)):
            placeholder = f"__CODE_BLOCK_{i}__"
            code_blocks[placeholder] = match.group()
            protected_text = protected_text.replace(match.group(), placeholder, 1)

        # Step 2: Split by headers first
        sections = self._split_by_headers(protected_text)

        # Step 3: Process each section into chunks
        chunks: list[ChunkData] = []
        current_pos = 0

        for section in sections:
            # Restore code blocks
            restored_section = section
            for placeholder, code in code_blocks.items():
                restored_section = restored_section.replace(placeholder, code)

            # Split section into appropriately sized chunks
            section_chunks = self._split_section(restored_section, current_pos)
            chunks.extend(section_chunks)
            current_pos += len(restored_section)

        # Step 3.5: Hard-split oversized chunks to fit embedding ctx ceiling (B1)
        chunks = self._hard_split_chunks(chunks)

        # Step 4: Assign indices and add overlap
        final_chunks = self._apply_overlap(chunks)

        # Step 5: Enrich metadata and Quality Scoring
        for chunk in final_chunks:
            chunk.metadata["document_title"] = document_title
            chunk.token_count = self.count_tokens(chunk.content)

            # Apply Quality Scoring
            quality_data = self.quality_scorer.grade_chunk(chunk.content)
            chunk.metadata.update(quality_data)

        return final_chunks

    def _split_by_headers(self, text: str) -> list[str]:
        """Split text by markdown headers."""
        # Find all header positions
        headers = list(self.HEADER_PATTERN.finditer(text))

        if not headers:
            return [text]

        sections = []
        prev_end = 0

        for match in headers:
            # Add content before this header
            if match.start() > prev_end:
                before = text[prev_end : match.start()].strip()
                if before:
                    sections.append(before)
            prev_end = match.start()

        # Add remaining content
        if prev_end < len(text):
            sections.append(text[prev_end:].strip())

        return [s for s in sections if s]

    def _split_section(self, section: str, start_offset: int) -> list[ChunkData]:
        """Split a section into chunks respecting size limits."""
        tokens = self.count_tokens(section)

        # If section fits, return as single chunk
        if tokens <= self.chunk_size:
            return [
                ChunkData(
                    content=section.strip(),
                    index=0,  # Will be reassigned later
                    start_char=start_offset,
                    end_char=start_offset + len(section),
                    token_count=tokens,
                )
            ]

        # Split by paragraphs
        paragraphs = self.PARAGRAPH_PATTERN.split(section)
        chunks = []
        current_chunk = ""
        chunk_start = start_offset

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            test_chunk = current_chunk + "\n\n" + para if current_chunk else para
            test_tokens = self.count_tokens(test_chunk)

            if test_tokens <= self.chunk_size:
                current_chunk = test_chunk
            else:
                # Check if the new paragraph ITSELF is too large
                if self.count_tokens(para) > self.chunk_size:
                    # Fix for orphan headers:
                    # If we have a current_chunk (e.g. "## Header") and the new para is huge,
                    # don't emit "## Header" alone. Combine them and split the whole block by sentences.

                    combined_text = current_chunk + "\n\n" + para if current_chunk else para

                    # We need to trace back the start char for the combined block
                    # If current_chunk exists, it starts at chunk_start.
                    # If not, it starts at chunk_start (which matches the loop invariant).

                    sentence_chunks = self._split_by_sentences(combined_text, chunk_start)
                    chunks.extend(sentence_chunks)

                    # Update Start Offset
                    chunk_start += len(combined_text)
                    current_chunk = ""

                else:
                    # Normal Case: new para doesn't fit in current one, but fits in a new one
                    if current_chunk:
                        chunks.append(
                            ChunkData(
                                content=current_chunk.strip(),
                                index=0,
                                start_char=chunk_start,
                                end_char=chunk_start + len(current_chunk),
                                token_count=self.count_tokens(current_chunk),
                            )
                        )
                        chunk_start += len(current_chunk)

                        # Add the \n\n skipped?
                        # Logic in loop: `para` comes from split(\n\n).
                        # We need to account for the separators length in `chunk_start` if we want exact precision,
                        # but typically `len(current_chunk)` updates appropriately if current_chunk INCLUDES the separators.
                        # Wait, `test_chunk = current_chunk + "\n\n" + para`.
                        # If we reset current_chunk to `para`, we technically skipped the `\n\n` between old `current` and `para` in the previous block.
                        # Actually previous logic `chunk_start += len(current_chunk)` might have drifted if we didn't include separators.
                        # But let's stick to the minimal fix logic:

                        # Re-calculate drift?
                        # `current_chunk` usually accumulated `\n\n` inside it?
                        # Yes: ` current_chunk = test_chunk` where `test_chunk` has `\n\n`.

                        # So simply:
                        current_chunk = para

        # Add remaining
        if current_chunk:
            chunks.append(
                ChunkData(
                    content=current_chunk.strip(),
                    index=0,
                    start_char=chunk_start,
                    end_char=chunk_start + len(current_chunk),
                    token_count=self.count_tokens(current_chunk),
                )
            )

        return chunks

    def _split_by_sentences(self, text: str, start_offset: int) -> list[ChunkData]:
        """Split text by sentences as last resort."""
        sentences = self.SENTENCE_PATTERN.split(text)
        chunks = []
        current_chunk = ""
        chunk_start = start_offset

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            test_chunk = current_chunk + " " + sentence if current_chunk else sentence

            if self.count_tokens(test_chunk) <= self.chunk_size:
                current_chunk = test_chunk
            else:
                if current_chunk:
                    chunks.append(
                        ChunkData(
                            content=current_chunk.strip(),
                            index=0,
                            start_char=chunk_start,
                            end_char=chunk_start + len(current_chunk),
                            token_count=self.count_tokens(current_chunk),
                        )
                    )
                    chunk_start += len(current_chunk)
                current_chunk = sentence

        if current_chunk:
            chunks.append(
                ChunkData(
                    content=current_chunk.strip(),
                    index=0,
                    start_char=chunk_start,
                    end_char=chunk_start + len(current_chunk),
                    token_count=self.count_tokens(current_chunk),
                )
            )

        return chunks

    def _apply_overlap(self, chunks: list[ChunkData]) -> list[ChunkData]:
        """Apply overlap between chunks and assign final indices."""
        if not chunks or self.chunk_overlap == 0:
            for i, chunk in enumerate(chunks):
                chunk.index = i
            return chunks

        # For overlap, we prepend tokens from previous chunk
        final_chunks = []

        for i, chunk in enumerate(chunks):
            chunk.index = i

            if i > 0 and self.chunk_overlap > 0:
                # Get overlap content from previous chunk
                prev_content = chunks[i - 1].content
                overlap_tokens = self._get_last_n_tokens(prev_content, self.chunk_overlap)
                if overlap_tokens:
                    chunk.content = overlap_tokens + "\n\n" + chunk.content
                    chunk.token_count = self.count_tokens(chunk.content)

            final_chunks.append(chunk)

        return final_chunks

    def _get_last_n_tokens(self, text: str, n: int) -> str:
        """Get approximately the last n tokens of text."""
        if self.encoder:
            tokens = self.encoder.encode(text)
            if len(tokens) <= n:
                return text
            return self.encoder.decode(tokens[-n:])
        else:
            # Word-based fallback
            words = text.split()
            return " ".join(words[-n:]) if len(words) > n else text

    def _hard_split_chunks(self, chunks: list[ChunkData]) -> list[ChunkData]:
        """Split chunks exceeding EMBED_TOKEN_CAP so they fit the embedding ctx.

        nomic-embed-text v1 caps at 2048 nomic tokens regardless of num_ctx; oversized
        chunks (big code blocks/tables) hit 400 and fail ingestion. Split contiguously so
        join(children) == parent content (no data loss). Normal chunks (<cap) untouched.
        """
        out: list[ChunkData] = []
        for chunk in chunks:
            # leave room for _apply_overlap which prepends chunk_overlap tokens AFTER this step
            cap = max(self.EMBED_TOKEN_CAP - self.chunk_overlap, 1)
            if self.count_tokens(chunk.content) <= cap:
                out.append(chunk)
                continue
            pieces = self._hard_split_text(chunk.content, cap)
            offset = chunk.start_char
            for piece in pieces:
                if not piece:
                    continue
                out.append(
                    ChunkData(
                        content=piece,
                        index=0,
                        start_char=offset,
                        end_char=offset + len(piece),
                        token_count=self.count_tokens(piece),
                        metadata=dict(chunk.metadata),
                    )
                )
                offset += len(piece)
        return out

    def _hard_split_text(self, text: str, cap: int | None = None) -> list[str]:
        """Recursively split text into pieces <= cap tokens.

        Separator hierarchy (coarse->fine): paragraph (\\n\\n), line (\\n),
        sentence, char. join(pieces) == text exactly. No data loss.
        """
        if cap is None:
            cap = self.EMBED_TOKEN_CAP
        if self.count_tokens(text) <= cap:
            return [text]

        # paragraph / line separators (keep sep attached to previous piece so join holds)
        for sep in ("\n\n", "\n"):
            pieces = self._split_keep(text, sep)
            if len(pieces) > 1:
                return self._pack_or_recurse(pieces, cap)

        # sentence separator
        sent_keep = []
        last = 0
        for m in self.SENTENCE_PATTERN.finditer(text):
            sent_keep.append(text[last : m.end()])
            last = m.end()
        sent_keep.append(text[last:])
        if len(sent_keep) > 1:
            return self._pack_or_recurse(sent_keep, cap, char_fallback=True)

        # single unbreakable string
        return self._char_split(text, cap)

    def _split_keep(self, text: str, sep: str) -> list[str]:
        """Split keeping separator attached to previous piece (join==text)."""
        parts = text.split(sep)
        return [p + sep for p in parts[:-1]] + [parts[-1]]

    def _pack_or_recurse(self, pieces: list[str], cap: int, char_fallback: bool = False) -> list[str]:
        """Greedily pack pieces into chunks <= cap; recurse oversized pieces."""
        out: list[str] = []
        cur = ""
        for p in pieces:
            if not p:
                continue
            if self.count_tokens(p) > cap:
                if cur:
                    out.append(cur)
                    cur = ""
                if char_fallback:
                    out.extend(self._char_split(p, cap))
                else:
                    out.extend(self._hard_split_text(p, cap))
            elif self.count_tokens(cur + p) <= cap:
                cur += p
            else:
                if cur:
                    out.append(cur)
                cur = p
        if cur:
            out.append(cur)
        return out

    def _char_split(self, text: str, cap: int) -> list[str]:
        """Last-resort: cut a single unbreakable string into <=cap-token pieces (join==text)."""
        if self.count_tokens(text) <= cap:
            return [text]
        lo, hi = 1, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.count_tokens(text[:mid]) <= cap:
                lo = mid
            else:
                hi = mid - 1
        n = max(lo, 1)
        head = text[:n]
        tail = text[n:]
        return [head] + self._char_split(tail, cap) if tail else [head]

    def _split_from_definitions(
        self, text: str, definitions: list[dict], document_title: str | None
    ) -> list[ChunkData]:
        """
        Split text based on pre-parsed definitions from Tree-Sitter.
        Generates chunks for each definition to ensure they are searchable.
        """
        chunks = []
        lines = text.splitlines(keepends=True)

        # We iterate through all definitions.
        # Note: This may create overlapping chunks (e.g. Class chunk + Method chunk),
        # which is actually beneficial for RAG (finding both the container and the leaf).

        # Build line offsets map
        line_offsets = []
        acc = 0
        for line in lines:
            line_offsets.append(acc)
            acc += len(line)
        line_offsets.append(acc)  # Sentinel for EOF

        # Helper to get char range from line numbers (1-indexed)
        def get_range(start_line, end_line):
            start_off = line_offsets[start_line - 1]
            end_off = line_offsets[
                end_line
            ]  # end_line is inclusive, so slice up to next line start
            return start_off, end_off

        for idx, defn in enumerate(definitions):
            start = defn["start_line"]
            end = defn["end_line"]

            # Clamp to valid range
            start = max(1, start)
            end = min(len(lines), end)

            if start > end:
                continue

            start_char, end_char = get_range(start, end)

            # Extract content directly from text to assume consistency
            content = text[start_char:end_char]

            chunks.append(
                ChunkData(
                    content=content,
                    index=idx,
                    start_char=start_char,
                    end_char=end_char,
                    token_count=self.count_tokens(content),
                    metadata={
                        "type": defn["type"],
                        "name": defn["name"],
                        "start_line": start,
                        "end_line": end,
                        "document_title": document_title,
                    },
                )
            )

        return chunks
