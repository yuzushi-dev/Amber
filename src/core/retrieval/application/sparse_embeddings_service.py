"""
Sparse Embedding Service
========================

Service for generating sparse embeddings (SPLADE) for Hybrid Search.
Uses a Masked Language Model to generate token weights.
"""

import logging

try:
    import torch
    from transformers import AutoModelForMaskedLM, AutoTokenizer

    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

logger = logging.getLogger(__name__)


class SparseEmbeddingService:
    """
    Service to generate sparse embeddings using SPLADE model.
    Returns: Dict[int, float] mapping token_id -> weight.
    """

    # Lightweight SPLADE model
    DEFAULT_MODEL = "naver/splade-cocondenser-ensembledistil"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self._tokenizer = None
        self._model = None
        self._device = "cpu"

        if not HAS_DEPS:
            logger.warning(
                "SparseEmbeddingService initialized without torch/transformers. Usage will fail."
            )
        else:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

    def _load_model(self):
        """Lazy load the model."""
        if self._model is not None:
            return

        if not HAS_DEPS:
            raise ImportError("torch and transformers are required for SparseEmbeddingService")

        logger.info(f"Loading SPLADE model: {self.model_name} on {self._device}")
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForMaskedLM.from_pretrained(self.model_name)
            self._model.to(self._device)
            self._model.eval()
        except Exception as e:
            logger.error(f"Failed to load SPLADE model: {e}")
            raise

    def prewarm(self) -> bool:
        """
        Pre-load the SPLADE model to avoid cold-start delays on first query.

        Returns:
            bool: True if model was loaded successfully, False otherwise.
        """
        if not HAS_DEPS:
            logger.warning("Cannot prewarm SPLADE: torch/transformers not available")
            return False

        try:
            self._load_model()
            logger.info(f"SPLADE model prewarmed successfully on {self._device}")
            return True
        except Exception as e:
            logger.error(f"Failed to prewarm SPLADE model: {e}")
            return False

    def embed_sparse(self, text: str) -> dict[int, float]:
        """
        Generate sparse embedding for a single text.
        """
        results = self.embed_batch([text])
        return results[0] if results else {}

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[dict[int, float]]:
        """
        Generate sparse embeddings for a batch of texts.
        """
        if not texts:
            return []

        self._load_model()
        results = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]

            try:
                # Tokenize
                tokens = self._tokenizer(
                    batch_texts, return_tensors="pt", padding=True, truncation=True, max_length=512
                ).to(self._device)

                with torch.no_grad():
                    # Inference
                    logits = self._model(**tokens).logits  # [batch, seq_len, vocab_size]

                    # SPLADE Formula: max(log(1 + relu(logits))) over sequence
                    # 1. ReLU
                    relu_log = torch.log(1 + torch.relu(logits))

                    # 2. Mask attention (ignore padding)
                    attention_mask = tokens.attention_mask.unsqueeze(-1)  # [batch, seq_len, 1]
                    weighted_log = relu_log * attention_mask

                    # 3. Max pooling over sequence dimension
                    max_val, _ = torch.max(weighted_log, dim=1)  # [batch, vocab_size]

                    # 4. Filter zero weights and format
                    for vector in max_val:
                        # Get non-zero indices
                        indices = torch.nonzero(vector).squeeze()  # [num_nonzero] or []

                        if indices.dim() == 0:
                            # Handle scalar case (1 non-zero element) or empty
                            if indices.numel() == 1:
                                indices = indices.unsqueeze(0)
                            else:
                                # All zeros or empty
                                results.append({})
                                continue

                        values = vector[indices]

                        # Handle case where values might be scalar
                        if values.dim() == 0:
                            values = values.unsqueeze(0)

                        # Convert to dict
                        sparse_vector = {
                            int(idx): float(val)
                            for idx, val in zip(indices.tolist(), values.tolist(), strict=False)
                            if val > 0
                        }
                        results.append(sparse_vector)

            except Exception as e:
                logger.error(f"Error generating sparse embedding batch: {e}")
                # Append empty dicts for the failed batch to maintain alignment
                results.extend([{}] * len(batch_texts))

        return results

    def get_token_map(self, sparse_vector: dict[int, float]) -> dict[str, float]:
        """Convert token IDs to string tokens for debugging."""
        if not self._tokenizer:
            return {}

        return {self._tokenizer.decode([k]): v for k, v in sparse_vector.items()}
