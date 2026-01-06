"""
Entity and Relationship data models for entity extraction.

This module defines the core data structures used throughout the entity extraction
and graph RAG pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Entity:
    """Represents an extracted entity."""

    name: str
    type: str
    description: str
    importance_score: float = 0.5
    source_text_units: List[str] = field(default_factory=list)
    source_chunks: List[str] = field(default_factory=list)

    def __post_init__(self):
        # Fix mutable defaults if they were passed as None or shared
        if self.source_text_units is None:
            self.source_text_units = []
        else:
            self.source_text_units = list(self.source_text_units)
            
        if self.source_chunks is None:
            self.source_chunks = []
        else:
            self.source_chunks = list(self.source_chunks)
            
        # Ensure semantic equivalence between text units and chunks if one is missing
        if not self.source_text_units and self.source_chunks:
            self.source_text_units = list(self.source_chunks)
        if not self.source_chunks and self.source_text_units:
            self.source_chunks = list(self.source_text_units)


@dataclass
class Relationship:
    """Represents a relationship between two entities."""

    source_entity: str
    target_entity: str
    relationship_type: str
    description: str
    strength: float = 0.5
    source_text_units: List[str] = field(default_factory=list)
    source_chunks: List[str] = field(default_factory=list)

    def __post_init__(self):
        # Fix mutable defaults
        if self.source_text_units is None:
            self.source_text_units = []
        else:
            self.source_text_units = list(self.source_text_units)
            
        if self.source_chunks is None:
            self.source_chunks = []
        else:
            self.source_chunks = list(self.source_chunks)
            
        # Ensure semantic equivalence
        if not self.source_text_units and self.source_chunks:
            self.source_text_units = list(self.source_chunks)
        if not self.source_chunks and self.source_text_units:
            self.source_chunks = list(self.source_text_units)
