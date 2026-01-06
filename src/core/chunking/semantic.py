"""
Semantic Chunker
================

Structure-aware text chunking that respects document hierarchy.
"""

import re
import logging
from typing import List, Optional
from dataclasses import dataclass, field

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

from src.core.intelligence.strategies import ChunkingStrategy
from src.core.chunking.quality import ChunkQualityScorer

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
    HEADER_PATTERN = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    CODE_BLOCK_PATTERN = re.compile(r'```[\s\S]*?```', re.MULTILINE)
    PARAGRAPH_PATTERN = re.compile(r'\n\n+')
    SENTENCE_PATTERN = re.compile(r'(?<=[.!?])\s+')

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
            self.encoder = tiktoken.get_encoding(encoding_name)
        else:
            self.encoder = None
            logger.warning("tiktoken not available, using word-based estimation")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if self.encoder:
            return len(self.encoder.encode(text))
        # Fallback: rough word-based estimate
        return len(text.split())

    def chunk(self, text: str, document_title: Optional[str] = None) -> List[ChunkData]:
        """
        Split text into semantic chunks.
        
        Args:
            text: Full document text.
            document_title: Optional title for context enrichment.
            
        Returns:
            List of ChunkData objects.
        """
        if not text or not text.strip():
            return []

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
        chunks: List[ChunkData] = []
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

    def _split_by_headers(self, text: str) -> List[str]:
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
                before = text[prev_end:match.start()].strip()
                if before:
                    sections.append(before)
            prev_end = match.start()
        
        # Add remaining content
        if prev_end < len(text):
            sections.append(text[prev_end:].strip())
        
        return [s for s in sections if s]

    def _split_section(self, section: str, start_offset: int) -> List[ChunkData]:
        """Split a section into chunks respecting size limits."""
        tokens = self.count_tokens(section)
        
        # If section fits, return as single chunk
        if tokens <= self.chunk_size:
            return [ChunkData(
                content=section.strip(),
                index=0,  # Will be reassigned later
                start_char=start_offset,
                end_char=start_offset + len(section),
                token_count=tokens
            )]
        
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
                # Save current chunk
                if current_chunk:
                    chunks.append(ChunkData(
                        content=current_chunk.strip(),
                        index=0,
                        start_char=chunk_start,
                        end_char=chunk_start + len(current_chunk),
                        token_count=self.count_tokens(current_chunk)
                    ))
                    chunk_start += len(current_chunk)
                
                # Handle paragraph that's too large
                if self.count_tokens(para) > self.chunk_size:
                    # Split by sentences
                    sentence_chunks = self._split_by_sentences(para, chunk_start)
                    chunks.extend(sentence_chunks)
                    chunk_start += len(para)
                    current_chunk = ""
                else:
                    current_chunk = para
        
        # Add remaining
        if current_chunk:
            chunks.append(ChunkData(
                content=current_chunk.strip(),
                index=0,
                start_char=chunk_start,
                end_char=chunk_start + len(current_chunk),
                token_count=self.count_tokens(current_chunk)
            ))
        
        return chunks

    def _split_by_sentences(self, text: str, start_offset: int) -> List[ChunkData]:
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
                    chunks.append(ChunkData(
                        content=current_chunk.strip(),
                        index=0,
                        start_char=chunk_start,
                        end_char=chunk_start + len(current_chunk),
                        token_count=self.count_tokens(current_chunk)
                    ))
                    chunk_start += len(current_chunk)
                current_chunk = sentence
        
        if current_chunk:
            chunks.append(ChunkData(
                content=current_chunk.strip(),
                index=0,
                start_char=chunk_start,
                end_char=chunk_start + len(current_chunk),
                token_count=self.count_tokens(current_chunk)
            ))
        
        return chunks

    def _apply_overlap(self, chunks: List[ChunkData]) -> List[ChunkData]:
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
