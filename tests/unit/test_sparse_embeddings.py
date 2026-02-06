"""
Unit tests for SparseEmbeddingService with GPU batching.
"""

import os
from importlib.util import find_spec
from unittest.mock import patch

import pytest


# Test without actual model loading
class TestSparseEmbeddingServiceBatch:
    """Test the embed_batch method."""

    def test_embed_batch_empty_input(self):
        """Empty input should return empty list."""
        from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService

        with patch.object(SparseEmbeddingService, "_load_model"):
            service = SparseEmbeddingService()
            result = service.embed_batch([])
            assert result == []

    def test_embed_sparse_delegates_to_batch(self):
        """Single text should delegate to embed_batch."""
        from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService

        service = SparseEmbeddingService()

        # Mock embed_batch to verify it's called
        with patch.object(service, "embed_batch", return_value=[{1: 0.5}]) as mock_batch:
            result = service.embed_sparse("test text")
            mock_batch.assert_called_once_with(["test text"])
            assert result == {1: 0.5}

    def test_embed_sparse_returns_empty_on_empty_batch(self):
        """When batch returns empty list, embed_sparse returns empty dict."""
        from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService

        service = SparseEmbeddingService()

        with patch.object(service, "embed_batch", return_value=[]):
            result = service.embed_sparse("test text")
            assert result == {}


@pytest.mark.integration
class TestSparseEmbeddingServiceIntegration:
    """Integration tests (require torch and transformers)."""

    @pytest.fixture
    def service(self):
        """Create a real service instance."""
        if find_spec("torch") is None or find_spec("transformers") is None:
            pytest.skip("torch/transformers not available")

        from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService

        # Keep this deterministic for unit CI: run only with locally cached model artifacts.
        with patch.dict(os.environ, {"TRANSFORMERS_OFFLINE": "1", "HF_HUB_OFFLINE": "1"}):
            service = SparseEmbeddingService()
            if not service.prewarm():
                pytest.skip(
                    "Sparse model is not cached locally. Pre-download "
                    f"`{SparseEmbeddingService.DEFAULT_MODEL}` to run these tests."
                )
            return service

    def test_embed_batch_produces_results(self, service):
        """Batch should produce results for each input text."""
        texts = ["Hello world", "This is a test", "GPU acceleration"]
        results = service.embed_batch(texts)

        assert len(results) == 3
        for result in results:
            assert isinstance(result, dict)
            # Each result should have some non-zero weights
            assert len(result) > 0

    def test_embed_batch_consistency(self, service):
        """Results should be consistent between batch and single."""
        text = "Consistency test"

        single_result = service.embed_sparse(text)
        batch_result = service.embed_batch([text])[0]

        # Should be identical
        assert single_result == batch_result

    def test_embed_batch_larger_than_batch_size(self, service):
        """Should handle inputs larger than batch size."""
        # Create 40 texts (batch_size is 32)
        texts = [f"Text number {i}" for i in range(40)]
        results = service.embed_batch(texts, batch_size=8)

        assert len(results) == 40
        for result in results:
            assert isinstance(result, dict)
