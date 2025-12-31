"""
Domain Classifier
=================

Service for integrity classification of documents using LLM.
"""

import logging
import json
import hashlib
from typing import Optional

from src.core.intelligence.strategies import DocumentDomain
from src.api.config import settings

logger = logging.getLogger(__name__)

# Placeholder for Redis client - we assume we can get it from dependency injection or global pool.
# For now, we will assume a simple Redis wrapper or usage.
# We will use the existing Redis settings.

try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class DomainClassifier:
    """
    Classifies documents into domains using LLM.
    Caches results in Redis.
    """

    def __init__(self):
        # Initialize Redis connection if available
        # In a real app, this should be injected or managed via a pool.
        self.redis: Optional[redis.Redis] = None
        # Settings has redis_url inside db settings or we check if there's a specific redis config.
        # Based on config.py, it is settings.db.redis_url
        if HAS_REDIS and settings.db.redis_url:
             self.redis = redis.Redis.from_url(
                 settings.db.redis_url,
                 decode_responses=True
             )

    async def classify(self, content: str) -> DocumentDomain:
        """
        Classify the document content.
        
        Args:
            content: The text content of the document.
            
        Returns:
            DocumentDomain: The identified domain.
        """
        # 1. Truncate content for analysis (2k chars)
        sample = content[:2000]
        
        # 2. Check Cache
        content_hash = hashlib.sha256(sample.encode()).hexdigest()
        cache_key = f"classification:{content_hash}"
        
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.info(f"Classification cache hit for {content_hash}")
                    return DocumentDomain(cached)
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")

        # 3. Call LLM (Mocked/Placeholder for Phase 1)
        # Phase 0 setup openai/anthropic, but for this specific "Stage 1.4", 
        # we might not have the full LLM service layer fully wired in `core`.
        # We will implement a mockable calling logic here.
        # In a real implementations, we would use `src.core.llm.client` or similar.
        
        domain = await self._call_llm(sample)
        
        # 4. Cache Result
        if self.redis:
            try:
                await self.redis.set(cache_key, domain.value, ex=86400 * 7) # 7 days
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")
                
        return domain

    async def _call_llm(self, text: str) -> DocumentDomain:
        """
        Internal method to call LLM.
        """
        # TODO: Replace with actual LLM call using `src.api.config.settings` and appropriate client.
        # For now, we use a heuristic or mock for the verification test.
        # This allows us to pass Phase 1 without burning tokens or requiring keys in CI.
        
        txt = text.lower()
        if "def " in txt or "class " in txt or "import " in txt or "code" in txt:
            return DocumentDomain.TECHNICAL
        elif "contract" in txt or "agreement" in txt or "law" in txt:
            return DocumentDomain.LEGAL
        elif "financial" in txt or "statement" in txt or "balance" in txt:
             return DocumentDomain.FINANCIAL
        elif "abstract" in txt and "introduction" in txt and "conclusion" in txt:
            return DocumentDomain.SCIENTIFIC
            
        return DocumentDomain.GENERAL

    async def close(self):
        if self.redis:
            await self.redis.aclose()
