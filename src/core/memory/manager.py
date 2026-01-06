
"""
Conversation Memory Manager
===========================

Ports the Layered Memory System from the Reference codebase.
Manages persistent user facts and conversation summaries for context-aware retrieval.
Enforces strict Tenant Isolation.
"""

from typing import List, Optional, Dict, Any
from uuid import uuid4
import logging

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_session_maker
from src.core.models.memory import UserFact, ConversationSummary

logger = logging.getLogger(__name__)

class ConversationMemoryManager:
    """
    Manages long-term (facts) and mid-term (summaries) memory for user sessions.
    
    Layers:
    1. User Facts: Explicit facts learned about the user (e.g. "User is a python developer").
    2. Conversation Summaries: Summarized history of past interactions.
    """

    async def add_user_fact(
        self,
        tenant_id: str,
        user_id: str,
        content: str,
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UserFact:
        """
        Add a new permanent fact about the user.
        """
        fact_id = f"fact_{uuid4().hex[:12]}"
        
        async with get_session_maker()() as session:
            try:
                fact = UserFact(
                    id=fact_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    content=content,
                    importance=importance,
                    metadata_=metadata or {}
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
        limit: int = 20
    ) -> List[UserFact]:
        """
        Retrieve top user facts, strictly filtered by tenant_id.
        """
        async with get_session_maker()() as session:
            stmt = (
                select(UserFact)
                .where(UserFact.tenant_id == tenant_id)
                .where(UserFact.user_id == user_id)
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationSummary:
        """
        Persist a summary of a completed conversation.
        """
        async with get_session_maker()() as session:
            try:
                # Upsert logic could be added here, but for now we assume unique ID or new entry
                conv_summary = ConversationSummary(
                    id=conversation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    title=title,
                    summary=summary,
                    metadata_=metadata or {}
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
        self,
        tenant_id: str,
        user_id: str,
        limit: int = 5
    ) -> List[ConversationSummary]:
        """
        Retrieve user's recent conversation history summaries.
        """
        async with get_session_maker()() as session:
            stmt = (
                select(ConversationSummary)
                .where(ConversationSummary.tenant_id == tenant_id)
                .where(ConversationSummary.user_id == user_id)
                .order_by(desc(ConversationSummary.created_at))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

# Global Instance
memory_manager = ConversationMemoryManager()
