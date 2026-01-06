import logging

from src.core.providers.base import ProviderTier
from src.core.providers.factory import get_llm_provider

logger = logging.getLogger(__name__)

SUMMARIZE_ENTITY_PROMPT = """
Generic/Consolidated description required.
Summarize the following descriptions of the entity '{entity_name}' into a single, comprehensive description.
Avoid redundancy. Keep it concise (under 50 words).
Focus on what the entity IS and its key attributes.

Descriptions:
{descriptions}
"""

class EntitySummarizer:
    """Service to summarize multiple descriptions of the same entity."""

    async def summarize(self, name: str, descriptions: list[str]) -> str:
        """
        Consolidate multiple descriptions into one.

        Args:
            name: Name of the entity
            descriptions: List of description strings

        Returns:
            Consolidated description string
        """
        if not descriptions:
            return ""

        # Deduplicate generic strings
        unique_descs = list({d.strip() for d in descriptions if d and d.strip()})

        if not unique_descs:
            return ""

        if len(unique_descs) == 1:
            return unique_descs[0]

        # If we have meaningful variations, use LLM to summarize
        # Use Economy tier for summarization
        provider = get_llm_provider(tier=ProviderTier.ECONOMY)

        text_blob = "\n- ".join(unique_descs)

        try:
            res = await provider.generate(
                prompt=SUMMARIZE_ENTITY_PROMPT.format(entity_name=name, descriptions=text_blob),
                max_tokens=150,
                temperature=0.3
            )
            return res.text.strip()
        except Exception as e:
            logger.warning(f"Summarization failed for {name}: {e}")
            # Fallback: return the longest description or the first one
            return max(unique_descs, key=len)

entity_summarizer = EntitySummarizer()
