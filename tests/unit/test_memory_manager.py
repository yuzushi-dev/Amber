"""
Unit tests for ConversationMemoryManager.
Tests memory persistence, retrieval, and tenant isolation with mocked database.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.generation.domain.memory_models import ConversationSummary, UserFact


class TestConversationMemoryManager:
    """Tests for the ConversationMemoryManager class."""

    @pytest.fixture
    def mock_session_maker(self):
        """Create a mock session maker that returns an async context manager."""
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()

        # Make the session factory return a context manager
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        return mock_session_factory, mock_session

    @pytest.mark.asyncio
    async def test_add_user_fact_success(self, mock_session_maker):
        """Test adding a user fact successfully."""
        mock_factory, mock_session = mock_session_maker

        with patch("src.core.generation.application.memory.manager.get_session_maker", return_value=mock_factory):
            from src.core.generation.application.memory.manager import ConversationMemoryManager

            manager = ConversationMemoryManager()

            # Mock the refresh to not fail
            mock_session.refresh = AsyncMock()

            await manager.add_user_fact(
                tenant_id="tenant_1",
                user_id="user_1",
                content="User prefers Python.",
                importance=0.9
            )

            # Verify session.add was called
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

            # Verify the fact was created with correct attributes
            added_fact = mock_session.add.call_args[0][0]
            assert isinstance(added_fact, UserFact)
            assert added_fact.tenant_id == "tenant_1"
            assert added_fact.user_id == "user_1"
            assert added_fact.content == "User prefers Python."
            assert added_fact.importance == 0.9

    @pytest.mark.asyncio
    async def test_add_user_fact_default_importance(self, mock_session_maker):
        """Test that default importance is 0.5."""
        mock_factory, mock_session = mock_session_maker

        with patch("src.core.generation.application.memory.manager.get_session_maker", return_value=mock_factory):
            from src.core.generation.application.memory.manager import ConversationMemoryManager

            manager = ConversationMemoryManager()
            mock_session.refresh = AsyncMock()

            await manager.add_user_fact(
                tenant_id="tenant_1",
                user_id="user_1",
                content="Some fact"
            )

            added_fact = mock_session.add.call_args[0][0]
            assert added_fact.importance == 0.5

    @pytest.mark.asyncio
    async def test_get_user_facts_queries_correctly(self, mock_session_maker):
        """Test that get_user_facts uses correct query filters."""
        mock_factory, mock_session = mock_session_maker

        with patch("src.core.generation.application.memory.manager.get_session_maker", return_value=mock_factory):
            from src.core.generation.application.memory.manager import ConversationMemoryManager

            manager = ConversationMemoryManager()

            # Mock execute to return empty result
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)

            results = await manager.get_user_facts(
                tenant_id="tenant_1",
                user_id="user_1",
                limit=10
            )

            # Verify execute was called
            mock_session.execute.assert_called_once()
            assert results == []

    @pytest.mark.asyncio
    async def test_get_user_facts_returns_facts(self, mock_session_maker):
        """Test that get_user_facts returns facts from query."""
        mock_factory, mock_session = mock_session_maker

        with patch("src.core.generation.application.memory.manager.get_session_maker", return_value=mock_factory):
            from src.core.generation.application.memory.manager import ConversationMemoryManager

            manager = ConversationMemoryManager()

            # Create mock facts
            mock_fact1 = MagicMock(spec=UserFact)
            mock_fact1.content = "Fact 1"
            mock_fact2 = MagicMock(spec=UserFact)
            mock_fact2.content = "Fact 2"

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_fact1, mock_fact2]
            mock_session.execute = AsyncMock(return_value=mock_result)

            results = await manager.get_user_facts(
                tenant_id="tenant_1",
                user_id="user_1"
            )

            assert len(results) == 2
            assert results[0].content == "Fact 1"
            assert results[1].content == "Fact 2"

    @pytest.mark.asyncio
    async def test_save_conversation_summary_success(self, mock_session_maker):
        """Test saving a conversation summary successfully."""
        mock_factory, mock_session = mock_session_maker

        with patch("src.core.generation.application.memory.manager.get_session_maker", return_value=mock_factory):
            from src.core.generation.application.memory.manager import ConversationMemoryManager

            manager = ConversationMemoryManager()
            mock_session.refresh = AsyncMock()

            await manager.save_conversation_summary(
                tenant_id="tenant_1",
                user_id="user_1",
                conversation_id="conv_123",
                title="Python Discussion",
                summary="Discussed async patterns."
            )

            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

            added_summary = mock_session.add.call_args[0][0]
            assert isinstance(added_summary, ConversationSummary)
            assert added_summary.id == "conv_123"
            assert added_summary.tenant_id == "tenant_1"
            assert added_summary.title == "Python Discussion"
            assert added_summary.summary == "Discussed async patterns."

    @pytest.mark.asyncio
    async def test_get_recent_summaries_success(self, mock_session_maker):
        """Test retrieving recent conversation summaries."""
        mock_factory, mock_session = mock_session_maker

        with patch("src.core.generation.application.memory.manager.get_session_maker", return_value=mock_factory):
            from src.core.generation.application.memory.manager import ConversationMemoryManager

            manager = ConversationMemoryManager()

            # Create mock summaries
            mock_summary = MagicMock(spec=ConversationSummary)
            mock_summary.title = "Test Conversation"

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_summary]
            mock_session.execute = AsyncMock(return_value=mock_result)

            results = await manager.get_recent_summaries(
                tenant_id="tenant_1",
                user_id="user_1",
                limit=5
            )

            assert len(results) == 1
            assert results[0].title == "Test Conversation"


class TestUserFactModel:
    """Tests for the UserFact model."""

    def test_user_fact_creation(self):
        """Test UserFact model can be instantiated."""
        fact = UserFact(
            id="fact_123",
            tenant_id="tenant_1",
            user_id="user_1",
            content="Test content",
            importance=0.8,
            metadata_={"source": "test"}
        )

        assert fact.id == "fact_123"
        assert fact.tenant_id == "tenant_1"
        assert fact.user_id == "user_1"
        assert fact.content == "Test content"
        assert fact.importance == 0.8
        assert fact.metadata_["source"] == "test"

    def test_user_fact_repr(self):
        """Test UserFact string representation."""
        fact = UserFact(
            id="fact_123",
            tenant_id="tenant_1",
            user_id="user_1",
            content="This is a test fact for representation",
            importance=0.5
        )

        repr_str = repr(fact)
        assert "fact_123" in repr_str
        assert "user_1" in repr_str


class TestConversationSummaryModel:
    """Tests for the ConversationSummary model."""

    def test_conversation_summary_creation(self):
        """Test ConversationSummary model can be instantiated."""
        summary = ConversationSummary(
            id="conv_123",
            tenant_id="tenant_1",
            user_id="user_1",
            title="Test Conversation",
            summary="This is a test summary.",
            metadata_={"message_count": 10}
        )

        assert summary.id == "conv_123"
        assert summary.tenant_id == "tenant_1"
        assert summary.title == "Test Conversation"
        assert summary.summary == "This is a test summary."
        assert summary.metadata_["message_count"] == 10

    def test_conversation_summary_repr(self):
        """Test ConversationSummary string representation."""
        summary = ConversationSummary(
            id="conv_456",
            tenant_id="tenant_1",
            user_id="user_1",
            title="My Conversation",
            summary="Summary text"
        )

        repr_str = repr(summary)
        assert "conv_456" in repr_str
        assert "My Conversation" in repr_str
