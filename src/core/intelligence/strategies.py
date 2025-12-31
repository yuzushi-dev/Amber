"""
Chunking Strategies
===================

Definitions for domain-specific chunking strategies.
"""

from enum import Enum
from pydantic import BaseModel


class DocumentDomain(str, Enum):
    """
    Domains for document classification.
    """
    GENERAL = "general"
    TECHNICAL = "technical"
    LEGAL = "legal"
    FINANCIAL = "financial"
    SCIENTIFIC = "scientific"
    CONVERSATIONAL = "conversational"


class ChunkingStrategy(BaseModel):
    """
    Configuration for how to chunk a document.
    """
    chunk_size: int
    chunk_overlap: int
    name: str
    description: str


# Registry of strategies
STRATEGIES = {
    DocumentDomain.GENERAL: ChunkingStrategy(
        name="general",
        chunk_size=600,
        chunk_overlap=50,
        description="Balanced strategy for general text."
    ),
    DocumentDomain.LEGAL: ChunkingStrategy(
        name="legal",
        chunk_size=1000,
        chunk_overlap=100,
        description="Large chunks to capture full clauses and definitions."
    ),
    DocumentDomain.TECHNICAL: ChunkingStrategy(
        name="technical",
        chunk_size=800,
        chunk_overlap=50,
        description="Optimized for technical manuals and code blocks."
    ),
    DocumentDomain.FINANCIAL: ChunkingStrategy(
        name="financial",
        chunk_size=800,
        chunk_overlap=50,
        description="Optimized for tabular data and financial reports."
    ),
    DocumentDomain.SCIENTIFIC: ChunkingStrategy(
        name="scientific",
        chunk_size=1000,
        chunk_overlap=100,
        description="Optimized for research papers and sections."
    ),
    DocumentDomain.CONVERSATIONAL: ChunkingStrategy(
        name="conversational",
        chunk_size=500,
        chunk_overlap=100,
        description="Smaller chunks to capture dialogue flow."
    ),
}

def get_strategy(domain: str) -> ChunkingStrategy:
    """Get strategy by domain, defaulting to GENERAL."""
    try:
        return STRATEGIES[DocumentDomain(domain)]
    except (KeyError, ValueError):
        return STRATEGIES[DocumentDomain.GENERAL]
