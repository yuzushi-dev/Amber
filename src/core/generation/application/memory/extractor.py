"""
Memory Extractor
================

Service for extracting persistent user facts and summarizing conversations.
Uses LLMs to process text and extract structured memory.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from src.core.generation.application.memory.manager import memory_manager
from src.core.generation.application.prompts.templates import (
    CONVERSATION_SUMMARY_PROMPT,
    FACT_EXTRACTION_PROMPT,
)
from src.core.generation.domain.ports.provider_factory import get_llm_provider
from src.core.generation.domain.provider_models import ProviderTier
from src.core.security.pii_scrubber import PIIScrubber

logger = logging.getLogger(__name__)


class MemoryExtractor:
    """
    Handles extraction of facts and generation of summaries from conversation data.
    """

    def __init__(self):
        self._llm = None
        self.scrubber = PIIScrubber()

    @property
    def llm(self):
        if self._llm is None:
            self._llm = get_llm_provider(tier=ProviderTier.ECONOMY)
        return self._llm

    async def extract_and_save_facts(
        self,
        tenant_id: str,
        user_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        tenant_config: dict[str, Any] | None = None,
    ) -> list[str]:
        """
        Analyze text (usually a user query) for permanent user facts.
        If facts are found, save them to the database.

        Args:
            tenant_id: Tenant context
            user_id: User identity
            text: The text to analyze
            metadata: Optional metadata to attach to the fact

        Returns:
            List of extracted facts (strings)
        """
        if not text or len(text) < 10:
            return []

        # 1. Scrub PII before sending to LLM
        scrubbed_text = self.scrubber.scrub_text(text)

        # 2. Call LLM to extract facts
        try:
            prompt = FACT_EXTRACTION_PROMPT.format(user_input=scrubbed_text)
            logger.debug(f"Triggering fact extraction for user {user_id}")

            from src.core.generation.application.llm_steps import resolve_llm_step_config
            from src.core.generation.domain.ports.provider_factory import get_provider_factory
            from src.core.generation.domain.provider_models import ProviderTier
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
            tenant_config = tenant_config or {}
            llm_cfg = resolve_llm_step_config(
                tenant_config=tenant_config,
                step_id="memory.fact_extraction",
                settings=settings,
            )
            provider = get_provider_factory().get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
            kwargs: dict[str, Any] = {}
            if llm_cfg.temperature is not None:
                kwargs["temperature"] = llm_cfg.temperature
            if llm_cfg.seed is not None:
                kwargs["seed"] = llm_cfg.seed

            response = await provider.generate(
                prompt=prompt,
                max_tokens=256,
                **kwargs,
            )

            result = response.text.strip()
            logger.debug(f"Fact extraction raw response: {result}")

            # 3. Parse result
            if result == "NO_FACTS":
                logger.debug(f"No facts extracted for user {user_id}")
                return []

            try:
                # Handle potential markdown fencing
                if "```" in result:
                    result = result.split("```")[1].replace("json", "").strip()

                facts = json.loads(result)
                if not isinstance(facts, list):
                    logger.warning(f"Fact extraction returned non-list: {result}")
                    return []

            except json.JSONDecodeError:
                logger.warning(f"Failed to parse fact extraction JSON: {result}")
                return []

            # 4. Save valid facts
            saved_facts = []
            for fact in facts:
                if isinstance(fact, str) and len(fact) > 5:
                    await memory_manager.add_user_fact(
                        tenant_id=tenant_id, user_id=user_id, content=fact, metadata=metadata
                    )
                    saved_facts.append(fact)

            if saved_facts:
                logger.info(f"Extracted {len(saved_facts)} facts for user {user_id}: {saved_facts}")
            else:
                logger.debug(f"Extracted 0 valid facts for user {user_id}")

            return saved_facts

        except Exception as e:
            logger.error(f"Error during fact extraction for user {user_id}: {e}", exc_info=True)
            return []

    async def summarize_and_save_conversation(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        messages: list[dict[str, str]],
        title: str | None = None,
        tenant_config: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Summarize a conversation history and save it.

        Args:
            tenant_id: Tenant context
            user_id: User identity
            conversation_id: ID of the conversation
            messages: List of message dicts {"role": "...", "content": "..."}
            title: Optional title (will be generated if missing)

        Returns:
            The summary string if successful
        """
        if not messages:
            return None

        # Format messages for the prompt
        # Scrub PII from all messages
        formatted_history = ""
        for msg in messages:
            role = msg.get("role", "unknown")
            content = self.scrubber.scrub_text(msg.get("content", ""))
            formatted_history += f"{role.upper()}: {content}\n"

        try:
            # Generate Summary
            prompt = CONVERSATION_SUMMARY_PROMPT.format(history=formatted_history)
            logger.debug(f"Triggering conversation summarization for {conversation_id}")

            from src.core.generation.application.llm_steps import resolve_llm_step_config
            from src.core.generation.domain.ports.provider_factory import get_provider_factory
            from src.core.generation.domain.provider_models import ProviderTier
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
            tenant_config = tenant_config or {}
            llm_cfg = resolve_llm_step_config(
                tenant_config=tenant_config,
                step_id="memory.conversation_summary",
                settings=settings,
            )
            provider = get_provider_factory().get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
            kwargs: dict[str, Any] = {}
            if llm_cfg.temperature is not None:
                kwargs["temperature"] = llm_cfg.temperature
            if llm_cfg.seed is not None:
                kwargs["seed"] = llm_cfg.seed

            response = await provider.generate(
                prompt=prompt,
                max_tokens=512,
                **kwargs,
            )

            summary = response.text.strip()
            logger.debug(f"Summarization result: {summary[:100]}...")

            # Generate Title if missing (simple extraction)
            final_title = title
            if not final_title:
                # Use the first 50 chars of the first user message or a generic one
                first_user_msg = next((m for m in messages if m.get("role") == "user"), None)
                if first_user_msg:
                    raw_title = first_user_msg.get("content", "")[:50]
                    final_title = self.scrubber.scrub_text(raw_title)
                else:
                    final_title = f"Conversation {datetime.now(UTC).strftime('%Y-%m-%d')}"

            # Save to DB
            await memory_manager.save_conversation_summary(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                title=final_title,
                summary=summary,
                metadata={"message_count": len(messages)},
            )
            logger.info(f"Saved conversation summary for {conversation_id}")

            return summary

        except Exception as e:
            logger.error(f"Error during conversation summarization: {e}", exc_info=True)
            return None


# Global instance
memory_extractor = MemoryExtractor()
