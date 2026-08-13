"""
Conversation Memory Manager
===========================

Ports the Layered Memory System from the Reference codebase.
Manages persistent user facts and conversation summaries for context-aware retrieval.
Enforces strict Tenant Isolation.
"""

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session_maker
from src.core.generation.domain.memory_models import ConversationSummary, UserFact

logger = logging.getLogger(__name__)


class ConversationMemoryManager:
    """
    Manages long-term (facts) and mid-term (summaries) memory for user sessions.

    Layers:
    1. User Facts: Explicit facts learned about the user (e.g. "User is a python developer").
    2. Conversation Summaries: Summarized history of past interactions.
    """

    async def _configure_session(self, session: AsyncSession, tenant_id: str) -> None:
        """Apply request-equivalent tenant context for RLS-protected memory tables."""
        await session.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
            {"tenant_id": tenant_id},
        )

    async def add_user_fact(
        self,
        tenant_id: str,
        user_id: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        api_key_id: str | None = None,
    ) -> UserFact:
        """
        Add a new permanent fact about the user.
        """
        if not api_key_id:
            raise ValueError("Authenticated API-key ownership is required for user facts")

        fact_id = f"fact_{uuid4().hex[:12]}"

        async with get_session_maker()() as session:
            try:
                await self._configure_session(session, tenant_id)
                fact = UserFact(
                    id=fact_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    content=content,
                    importance=importance,
                    metadata_=metadata or {},
                )
                session.add(fact)
                await session.commit()
                await session.refresh(fact)
                logger.info(f"Added user fact {fact_id} for user {user_id} (tenant {tenant_id})")
                return fact
            except Exception as e:
                logger.error(f"Failed to add user fact: {e}")
                await session.rollback()
                raise

    async def get_user_facts(
        self,
        tenant_id: str,
        user_id: str,
        limit: int = 20,
        session: AsyncSession | None = None,
        api_key_id: str | None = None,
    ) -> list[UserFact]:
        """
        Retrieve top user facts, strictly filtered by tenant_id.
        """
        if not api_key_id:
            return []

        if session is not None:
            return await self._get_user_facts(session, tenant_id, user_id, api_key_id, limit)

        async with get_session_maker()() as session:
            await self._configure_session(session, tenant_id)
            return await self._get_user_facts(session, tenant_id, user_id, api_key_id, limit)

    @staticmethod
    async def _get_user_facts(
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        api_key_id: str | None,
        limit: int,
    ) -> list[UserFact]:
        if not api_key_id:
            return []

        stmt = (
            select(UserFact)
            .where(UserFact.tenant_id == tenant_id)
            .where(UserFact.user_id == user_id)
            .where(UserFact.api_key_id == api_key_id)
            .order_by(desc(UserFact.importance), desc(UserFact.created_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def save_conversation_summary(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        title: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
        api_key_id: str | None = None,
    ) -> ConversationSummary:
        """
        Persist a summary of a completed conversation.
        """
        if not api_key_id:
            raise ValueError("Authenticated API-key ownership is required for conversation summaries")

        async with get_session_maker()() as session:
            try:
                await self._configure_session(session, tenant_id)
                # Upsert logic could be added here, but for now we assume unique ID or new entry
                conv_summary = ConversationSummary(
                    id=conversation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    title=title,
                    summary=summary,
                    metadata_=metadata or {},
                )
                session.add(conv_summary)
                await session.commit()
                await session.refresh(conv_summary)
                logger.info(f"Saved summary for conversation {conversation_id}")
                return conv_summary
            except Exception as e:
                logger.error(f"Failed to save conversation summary: {e}")
                await session.rollback()
                raise

    async def get_recent_summaries(
        self, tenant_id: str, user_id: str, limit: int = 5, api_key_id: str | None = None
    ) -> list[ConversationSummary]:
        """
        Retrieve user's recent conversation history summaries.
        """
        if not api_key_id:
            return []

        async with get_session_maker()() as session:
            await self._configure_session(session, tenant_id)
            stmt = (
                select(ConversationSummary)
                .where(ConversationSummary.tenant_id == tenant_id)
                .where(ConversationSummary.user_id == user_id)
                .where(ConversationSummary.api_key_id == api_key_id)
                .order_by(desc(ConversationSummary.created_at))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_user_fact(self, tenant_id: str, fact_id: str) -> bool:
        """
        Delete a specific user fact.
        """
        async with get_session_maker()() as session:
            try:
                await self._configure_session(session, tenant_id)
                stmt = select(UserFact).where(
                    UserFact.id == fact_id, UserFact.tenant_id == tenant_id
                )
                result = await session.execute(stmt)
                fact = result.scalar_one_or_none()

                if fact:
                    await session.delete(fact)
                    await session.commit()
                    logger.info(f"Deleted user fact {fact_id} (tenant {tenant_id})")
                    return True
                return False
            except Exception as e:
                logger.error(f"Failed to delete user fact: {e}")
                await session.rollback()
                raise

    async def delete_conversation_summary(self, tenant_id: str, summary_id: str) -> bool:
        """
        Delete a conversation summary.
        """
        async with get_session_maker()() as session:
            try:
                await self._configure_session(session, tenant_id)
                stmt = select(ConversationSummary).where(
                    ConversationSummary.id == summary_id, ConversationSummary.tenant_id == tenant_id
                )
                result = await session.execute(stmt)
                summary = result.scalar_one_or_none()

                if summary:
                    await session.delete(summary)
                    await session.commit()
                    logger.info(f"Deleted conversation summary {summary_id} (tenant {tenant_id})")
                    return True
                return False
            except Exception as e:
                logger.error(f"Failed to delete conversation summary: {e}")
                await session.rollback()
                raise


# Global Instance
memory_manager = ConversationMemoryManager()
