"""
Unit tests for SparseEmbeddingService with GPU batching.
"""

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
    """Integration-style tests (torch path without network/model downloads)."""

    @pytest.fixture
    def service(self):
        """Create a service with deterministic local tokenizer/model stubs."""
        if find_spec("torch") is None or find_spec("transformers") is None:
            pytest.skip("torch/transformers not available")

        import torch

        from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService

        class DummyBatch(dict):
            def __init__(self, input_ids: "torch.Tensor", attention_mask: "torch.Tensor"):
                super().__init__(input_ids=input_ids, attention_mask=attention_mask)
                self.attention_mask = attention_mask

            def to(self, device: str):
                self["input_ids"] = self["input_ids"].to(device)
                self["attention_mask"] = self["attention_mask"].to(device)
                self.attention_mask = self["attention_mask"]
                return self

        class DummyTokenizer:
            def __init__(self, vocab_size: int = 128):
                self.vocab_size = vocab_size

            def _encode(self, text: str, max_length: int) -> list[int]:
                tokens = [
                    (sum(word.encode("utf-8")) % (self.vocab_size - 1)) + 1 for word in text.split()
                ]
                if not tokens:
                    return [1]
                return tokens[:max_length]

            def __call__(
                self,
                texts: list[str],
                *,
                return_tensors: str,
                padding: bool,
                truncation: bool,
                max_length: int,
            ) -> DummyBatch:
                assert return_tensors == "pt"
                assert padding and truncation
                encoded = [self._encode(text, max_length=max_length) for text in texts]
                max_len = max(len(row) for row in encoded)
                input_ids = torch.zeros((len(encoded), max_len), dtype=torch.long)
                attention_mask = torch.zeros((len(encoded), max_len), dtype=torch.long)
                for idx, row in enumerate(encoded):
                    row_tensor = torch.tensor(row, dtype=torch.long)
                    input_ids[idx, : len(row)] = row_tensor
                    attention_mask[idx, : len(row)] = 1
                return DummyBatch(input_ids=input_ids, attention_mask=attention_mask)

        class DummyModel(torch.nn.Module):
            def __init__(self, vocab_size: int = 128):
                super().__init__()
                self.vocab_size = vocab_size

            def forward(self, input_ids=None, attention_mask=None):
                del attention_mask
                clamped = input_ids.clamp(min=0, max=self.vocab_size - 1)
                one_hot = torch.nn.functional.one_hot(clamped, num_classes=self.vocab_size).float()
                logits = one_hot * 5.0
                return type("DummyOutput", (), {"logits": logits})

        service = SparseEmbeddingService(model_name="dummy-local-splade")
        service._tokenizer = DummyTokenizer()
        service._model = DummyModel()
        service._device = "cpu"
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
