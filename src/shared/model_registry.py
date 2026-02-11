from __future__ import annotations

from typing import Any

from src.shared.provider_models import ConfigurationError, ProviderTier

LLM_MODELS = {
    "openai": {
        "gpt-4o": {
            "tier": ProviderTier.STANDARD,
            "input_cost_per_1k": 0.005,
            "output_cost_per_1k": 0.015,
            "context_window": 128000,
            "description": "Most capable GPT-4 model",
        },
        "gpt-4o-mini": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.00015,
            "output_cost_per_1k": 0.0006,
            "context_window": 128000,
            "description": "Fast and cost-effective",
        },
        "gpt-4.1-mini": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.00015,
            "output_cost_per_1k": 0.0006,
            "context_window": 128000,
            "description": "Updated fast mini model",
        },
        "gpt-4.1-nano": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.00010,
            "output_cost_per_1k": 0.0004,
            "context_window": 128000,
            "description": "Updated compact nano model",
        },
        "gpt-5-mini": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.00015,
            "output_cost_per_1k": 0.0006,
            "context_window": 128000,
            "max_top_k": 3,
            "description": "Next-gen compact model",
        },
        "gpt-5-nano": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.00010,
            "output_cost_per_1k": 0.0004,
            "context_window": 128000,
            "max_top_k": 3,
            "description": "Ultra-efficient compact model",
        },
        "gpt-4-turbo": {
            "tier": ProviderTier.STANDARD,
            "input_cost_per_1k": 0.01,
            "output_cost_per_1k": 0.03,
            "context_window": 128000,
            "description": "GPT-4 Turbo with vision",
        },
        "o1": {
            "tier": ProviderTier.PREMIUM,
            "input_cost_per_1k": 0.015,
            "output_cost_per_1k": 0.06,
            "context_window": 200000,
            "description": "Reasoning model",
        },
    },
    "anthropic": {
        "claude-sonnet-4-20250514": {
            "tier": ProviderTier.STANDARD,
            "input_cost_per_1k": 0.003,
            "output_cost_per_1k": 0.015,
            "context_window": 200000,
            "description": "Claude Sonnet 4 - Best balance",
        },
        "claude-3-5-sonnet-20241022": {
            "tier": ProviderTier.STANDARD,
            "input_cost_per_1k": 0.003,
            "output_cost_per_1k": 0.015,
            "context_window": 200000,
            "description": "Claude 3.5 Sonnet",
        },
        "claude-3-5-haiku-20241022": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.0008,
            "output_cost_per_1k": 0.004,
            "context_window": 200000,
            "description": "Claude 3.5 Haiku - Fast and affordable",
        },
        "claude-3-opus-20240229": {
            "tier": ProviderTier.PREMIUM,
            "input_cost_per_1k": 0.015,
            "output_cost_per_1k": 0.075,
            "context_window": 200000,
            "description": "Claude 3 Opus - Most capable",
        },
    },
    "ollama": {
        "llama3": {
            "tier": ProviderTier.LOCAL,
            "description": "Meta Llama 3",
        },
        "mistral": {
            "tier": ProviderTier.LOCAL,
            "description": "Mistral 7B",
        },
        "phi3": {
            "tier": ProviderTier.LOCAL,
            "description": "Microsoft Phi-3",
        },
        "devstral-small-2:24b-cloud": {
            "tier": ProviderTier.LOCAL,
            "description": "Devstral (Mistral 24B)",
        },
    },
}

EMBEDDING_MODELS = {
    "openai": {
        "text-embedding-3-small": {
            "dimensions": 1536,
            "max_dimensions": 1536,
            "cost_per_1k": 0.00002,
            "supports_dimensions": True,
            "description": "Efficient, cost-effective embeddings",
        },
        "text-embedding-3-large": {
            "dimensions": 3072,
            "max_dimensions": 3072,
            "cost_per_1k": 0.00013,
            "supports_dimensions": True,
            "description": "High-quality embeddings with dimension flexibility",
        },
        "text-embedding-ada-002": {
            "dimensions": 1536,
            "max_dimensions": 1536,
            "cost_per_1k": 0.0001,
            "supports_dimensions": False,
            "description": "Legacy model",
        },
    },
    "ollama": {
        "nomic-embed-text": {
            "dimensions": 768,
            "max_dimensions": 768,
            "cost_per_1k": 0.0,
            "description": "Nomic's high quality text embeddings",
        },
        "mxbai-embed-large": {
            "dimensions": 1024,
            "max_dimensions": 1024,
            "cost_per_1k": 0.0,
            "description": "MixedBread AI large embeddings",
        },
        "all-minilm": {
            "dimensions": 384,
            "max_dimensions": 384,
            "cost_per_1k": 0.0,
            "description": "Fast, lightweight embeddings",
        },
        "snowflake-arctic-embed": {
            "dimensions": 1024,
            "max_dimensions": 1024,
            "cost_per_1k": 0.0,
            "description": "Snowflake Arctic embeddings",
        },
    },
    "local": {
        "BAAI/bge-m3": {
            "dimensions": 1024,
            "max_dimensions": 1024,
            "cost_per_1k": 0.0,
            "description": "Multilingual, high-quality local embeddings",
        },
        "BAAI/bge-large-en-v1.5": {
            "dimensions": 1024,
            "max_dimensions": 1024,
            "cost_per_1k": 0.0,
            "description": "English-focused, high quality",
        },
        "BAAI/bge-small-en-v1.5": {
            "dimensions": 384,
            "max_dimensions": 384,
            "cost_per_1k": 0.0,
            "description": "Fast, lightweight embeddings",
        },
        "sentence-transformers/all-MiniLM-L6-v2": {
            "dimensions": 384,
            "max_dimensions": 384,
            "cost_per_1k": 0.0,
            "description": "Popular lightweight model",
        },
    },
}

RERANKER_MODELS = {
    "flashrank": {
        "ms-marco-MiniLM-L-12-v2": {"description": "Default FlashRank model"},
        "ms-marco-MultiBERT-L-12": {"description": "Multilingual support"},
    }
}

DEFAULT_LLM_MODEL = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-3-5-haiku-20241022",
    "ollama": "llama3",
}

DEFAULT_EMBEDDING_MODEL = {
    "openai": "text-embedding-3-small",
    "ollama": "nomic-embed-text",
    "local": "BAAI/bge-m3",
}

DEFAULT_RERANKER_MODEL = {
    "flashrank": "ms-marco-MiniLM-L-12-v2",
}

DEFAULT_LLM_FALLBACKS = {
    ProviderTier.LOCAL: [("ollama", None)],
    ProviderTier.ECONOMY: [
        ("ollama", None),
        ("openai", "gpt-4.1-mini"),
        ("anthropic", "claude-3-5-haiku-20241022"),
    ],
    ProviderTier.STANDARD: [
        ("ollama", None),
        ("openai", "gpt-4o"),
        ("anthropic", "claude-sonnet-4-20250514"),
    ],
    ProviderTier.PREMIUM: [("anthropic", "claude-3-opus-20240229"), ("openai", "o1")],
}

DEFAULT_EMBEDDING_FALLBACK = [("openai", None), ("ollama", None), ("local", None)]

LEGACY_EMBEDDING_PROVIDERS = {
    "voyage-3.5-lite": "voyage",
}

LEGACY_EMBEDDING_DIMENSIONS = {
    "voyage-3.5-lite": 1536,
}

TOKEN_ENCODING_BY_PROVIDER = {
    "openai": "cl100k_base",
    "anthropic": "cl100k_base",
    "ollama": "cl100k_base",
    "local": "cl100k_base",
}

TOKEN_ENCODING_BY_MODEL = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
}

OPENAI_CHAT_MODEL_OVERRIDES: dict[str, dict[str, Any]] = {
    "o1": {"use_max_completion_tokens": True, "fixed_temperature": 1.0},
    "o3-mini": {"use_max_completion_tokens": True, "fixed_temperature": 1.0},
    "gpt-5-nano": {"use_max_completion_tokens": True, "fixed_temperature": 1.0},
    "gpt-5-mini": {"use_max_completion_tokens": True, "fixed_temperature": 1.0},
}


def _build_model_to_providers(catalog: dict[str, dict[str, dict]]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for provider, models in catalog.items():
        for name in models.keys():
            index.setdefault(name, set()).add(provider)
    return index


LLM_MODEL_TO_PROVIDERS = _build_model_to_providers(LLM_MODELS)
EMBEDDING_MODEL_TO_PROVIDERS = _build_model_to_providers(EMBEDDING_MODELS)


def resolve_provider_for_model(
    model: str, model_to_providers: dict[str, set[str]], *, kind: str
) -> str | None:
    """Resolve which provider owns a model.

    Returns None for models not in the registry — the caller should use
    the already-configured provider and let the provider itself reject
    invalid model names with a clear error.
    """
    providers = model_to_providers.get(model, set())
    if not providers:
        return None
    if len(providers) > 1:
        choices = ", ".join(sorted(providers))
        raise ConfigurationError(
            f"{kind}_model",
            f"Model '{model}' is available in providers [{choices}]. "
            f"Please set {kind}_provider or use provider:model syntax.",
        )
    return next(iter(providers))


def parse_fallback_chain(
    value: str | None,
    *,
    default: list[tuple[str, str | None]],
) -> list[tuple[str, str | None]]:
    if not value:
        return default
    chain: list[tuple[str, str | None]] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        if ":" in token:
            provider, model = token.split(":", 1)
            chain.append((provider.strip(), model.strip() or None))
        else:
            chain.append((token, None))
    return chain


def resolve_token_encoding(model: str | None) -> str | None:
    if not model:
        return None
    if model in TOKEN_ENCODING_BY_MODEL:
        return TOKEN_ENCODING_BY_MODEL[model]
    providers = LLM_MODEL_TO_PROVIDERS.get(model)
    if providers and len(providers) == 1:
        provider = next(iter(providers))
        return TOKEN_ENCODING_BY_PROVIDER.get(provider)
    providers = EMBEDDING_MODEL_TO_PROVIDERS.get(model)
    if providers and len(providers) == 1:
        provider = next(iter(providers))
        return TOKEN_ENCODING_BY_PROVIDER.get(provider)
    return None


def get_openai_chat_overrides(model: str) -> dict[str, Any]:
    overrides = OPENAI_CHAT_MODEL_OVERRIDES.get(model, {})
    return {
        "use_max_completion_tokens": bool(overrides.get("use_max_completion_tokens")),
        "fixed_temperature": overrides.get("fixed_temperature"),
    }


def embedding_supports_dimensions(model: str, *, provider: str | None = None) -> bool:
    if provider:
        return bool(EMBEDDING_MODELS.get(provider, {}).get(model, {}).get("supports_dimensions"))
    providers = EMBEDDING_MODEL_TO_PROVIDERS.get(model)
    if not providers or len(providers) != 1:
        return False
    provider = next(iter(providers))
    return bool(EMBEDDING_MODELS.get(provider, {}).get(model, {}).get("supports_dimensions"))
