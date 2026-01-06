"""
Cache Package
=============

Caching utilities for embeddings and retrieval results.
"""

from src.core.cache.result_cache import ResultCache
from src.core.cache.semantic_cache import SemanticCache

__all__ = ["SemanticCache", "ResultCache"]
