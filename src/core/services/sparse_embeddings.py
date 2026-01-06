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
            logger.warning("SparseEmbeddingService initialized without torch/transformers. Usage will fail.")
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

    def embed_sparse(self, text: str) -> dict[int, float]:
        """
        Generate sparse embedding for a single text.
        Returns dictionary of {token_id: weight}.
        """
        if not text:
            return {}

        self._load_model()

        try:
            # Tokenize
            tokens = self._tokenizer(
                text,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512
            ).to(self._device)

            with torch.no_grad():
                # Inference
                logits = self._model(**tokens).logits # [1, seq_len, vocab_size]

                # SPLADE Formula: max(log(1 + relu(logits))) over sequence
                # 1. ReLU
                relu_log = torch.log(1 + torch.relu(logits))

                # 2. Mask attention (ignore padding)
                attention_mask = tokens.attention_mask.unsqueeze(-1) # [1, seq_len, 1]
                weighted_log = relu_log * attention_mask

                # 3. Max pooling over sequence dimension
                max_val, _ = torch.max(weighted_log, dim=1) # [1, vocab_size]

                # 4. Filter zero weights and format
                # Squeeze batch dim
                vector = max_val.squeeze(0) # [vocab_size]

                # Get non-zero indices
                indices = torch.nonzero(vector).squeeze()

                if indices.dim() == 0: # Handle single token case
                    indices = indices.unsqueeze(0)

                values = vector[indices]

                # Convert to dict
                sparse_vector = {
                    int(idx): float(val)
                    for idx, val in zip(indices.tolist(), values.tolist(), strict=False)
                    if val > 0
                }

                return sparse_vector

        except Exception as e:
            logger.error(f"Error generating sparse embedding: {e}")
            return {}

    def get_token_map(self, sparse_vector: dict[int, float]) -> dict[str, float]:
        """Convert token IDs to string tokens for debugging."""
        if not self._tokenizer:
            return {}

        return {
            self._tokenizer.decode([k]): v
            for k, v in sparse_vector.items()
        }
