"""
Tests for DRIFT search timeout functionality.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDriftSearchTimeout:
    """Test suite for DRIFT search timeout behavior."""

    @pytest.fixture
    def mock_retrieval_service(self):
        service = MagicMock()
        service.retrieve = AsyncMock()
        return service

    @pytest.fixture
    def mock_llm_provider(self):
        provider = MagicMock()
        provider.generate = AsyncMock()
        return provider

    @pytest.fixture
    def mock_settings(self):
        settings = MagicMock()
        settings.default_llm_provider = "openai"
        return settings

    @pytest.mark.asyncio
    async def test_drift_has_timeout_config(self, mock_retrieval_service, mock_llm_provider):
        """Test that DriftSearchService accepts timeout_seconds parameter."""
        from src.core.retrieval.application.search.drift_search import DriftSearchService

        service = DriftSearchService(
            retrieval_service=mock_retrieval_service,
            llm_provider=mock_llm_provider,
            max_iterations=3,
            max_follow_ups=2,
            timeout_seconds=5.0,
        )

        assert service.timeout_seconds == 5.0

    @pytest.mark.asyncio
    async def test_drift_respects_timeout_deadline(self, mock_retrieval_service, mock_llm_provider, mock_settings):
        """Test that DRIFT search stops iterating when deadline is reached."""
        from src.core.retrieval.application.search.drift_search import DriftSearchService

        call_count = 0
        async def counting_retrieve(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.5)
            result = MagicMock()
            result.chunks = [{"chunk_id": str(call_count), "content": f"chunk {call_count}"}]
            return result

        mock_retrieval_service.retrieve = counting_retrieve
        mock_llm_provider.generate = AsyncMock(return_value=MagicMock(text="Q1\nQ2\nQ3"))

        with patch('src.shared.kernel.runtime.get_settings', return_value=mock_settings):
            service = DriftSearchService(
                retrieval_service=mock_retrieval_service,
                llm_provider=mock_llm_provider,
                max_iterations=10,
                max_follow_ups=3,
                timeout_seconds=1.0,
            )

            start = time.time()
            result = await service.search(
                query="test query",
                tenant_id="test-tenant",
            )
            elapsed = time.time() - start

            assert elapsed < 3.0, f"Should have completed in <3s, took {elapsed:.2f}s"
            assert len(result.get("candidates", [])) >= 1

    @pytest.mark.asyncio
    async def test_drift_completes_fast_when_under_timeout(self, mock_retrieval_service, mock_llm_provider, mock_settings):
        """Test that DRIFT search completes normally when operations are fast."""
        from src.core.retrieval.application.search.drift_search import DriftSearchService

        mock_retrieval_service.retrieve = AsyncMock(return_value=MagicMock(
            chunks=[{"chunk_id": "1", "content": "test"}]
        ))
        mock_llm_provider.generate = AsyncMock(return_value=MagicMock(text="DONE"))

        with patch('src.shared.kernel.runtime.get_settings', return_value=mock_settings):
            service = DriftSearchService(
                retrieval_service=mock_retrieval_service,
                llm_provider=mock_llm_provider,
                max_iterations=3,
                max_follow_ups=2,
                timeout_seconds=30.0,
            )

            start = time.time()
            result = await service.search(
                query="fast query",
                tenant_id="test-tenant",
            )
            elapsed = time.time() - start

            assert result is not None
            assert "candidates" in result
            assert elapsed < 2.0
