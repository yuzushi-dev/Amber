"""
Provider Discovery API
======================

Admin endpoints for discovering available LLM and embedding providers.
Returns only providers with valid configuration and their available models.
"""

import logging
from importlib.util import find_spec

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from urllib.parse import urlparse

from src.api.config import settings
from src.core.generation.infrastructure.providers.openai import (
    OpenAIEmbeddingProvider,
    OpenAILLMProvider,
)
from src.shared.model_registry import EMBEDDING_MODELS, LLM_MODELS

logger = logging.getLogger(__name__)

from src.api.deps import verify_super_admin
router = APIRouter(prefix="/providers", tags=["admin-providers"], dependencies=[Depends(verify_super_admin)])


# =============================================================================
# Schemas
# =============================================================================


class ProviderInfo(BaseModel):
    """Information about a provider."""

    name: str
    label: str
    available: bool
    error: str | None = None
    models: list[str] = []


class AvailableProvidersResponse(BaseModel):
    """Response with all available providers."""

    llm_providers: list[ProviderInfo]
    embedding_providers: list[ProviderInfo]


class ValidateProviderRequest(BaseModel):
    """Request to validate a specific provider."""

    provider_type: str  # "llm" or "embedding"
    provider_name: str


class ValidateProviderResponse(BaseModel):
    """Response from provider validation."""

    available: bool
    error: str | None = None
    models: list[str] = []


class OllamaTestRequest(BaseModel):
    """Request to test Ollama connectivity."""

    url: str  # e.g. "http://ollama-host:11434/v1"


# =============================================================================
# Helper Functions
# =============================================================================


def _ollama_label(base_url: str) -> str:
    """Generate a dynamic label for Ollama based on the configured URL."""
    parsed = urlparse(base_url)
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return "Ollama (Local)"
    return f"Ollama ({parsed.hostname})"


async def check_ollama_availability(
    base_url: str | None = None,
) -> tuple[bool, str, str | None, list[str], list[str]]:
    """
    Check if Ollama is available and list installed models.

    Args:
        base_url: Optional override URL. Falls back to settings.

    Returns:
        (available, label, error_message, llm_models, embedding_models)
    """
    url = (base_url or settings.ollama_base_url).rstrip("/v1")
    label = _ollama_label(base_url or settings.ollama_base_url)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/api/tags")

            if response.status_code != 200:
                return False, label, f"Ollama returned status {response.status_code}", [], []

            data = response.json()
            models = data.get("models", [])

            llm_models = []
            embedding_models = []

            for model in models:
                name = model.get("name", "")
                # Embedding models typically have "embed" in name
                if "embed" in name.lower():
                    embedding_models.append(name)
                else:
                    llm_models.append(name)

            return True, label, None, llm_models, embedding_models

    except httpx.ConnectError:
        return False, label, f"Cannot connect to Ollama at {url}", [], []
    except httpx.TimeoutException:
        return False, label, "Ollama connection timed out", [], []
    except Exception as e:
        return False, label, str(e), [], []


def check_openai_availability() -> tuple[bool, str | None]:
    """Check if OpenAI API key is configured."""
    if settings.openai_api_key and len(settings.openai_api_key) > 10:
        return True, None
    return False, "OpenAI API key not configured"


def check_anthropic_availability() -> tuple[bool, str | None]:
    """Check if Anthropic API key is configured."""
    if settings.anthropic_api_key and len(settings.anthropic_api_key) > 10:
        return True, None
    return False, "Anthropic API key not configured"


def check_local_embeddings_availability() -> tuple[bool, str | None]:
    """Check if local embedding provider is available."""
    if find_spec("sentence_transformers") is None:
        return False, "Local embeddings not available: sentence_transformers package missing"
    return True, None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/available", response_model=AvailableProvidersResponse)
async def get_available_providers():
    """
    Get all available LLM and embedding providers.

    Returns only providers that have valid configuration (API keys, connectivity).
    For each provider, returns the list of available models.
    """
    llm_providers: list[ProviderInfo] = []
    embedding_providers: list[ProviderInfo] = []

    # Check OpenAI
    openai_available, openai_error = check_openai_availability()
    if openai_available:
        llm_providers.append(
            ProviderInfo(
                name="openai",
                label="OpenAI",
                available=True,
                models=list(OpenAILLMProvider.models.keys()),
            )
        )
        embedding_providers.append(
            ProviderInfo(
                name="openai",
                label="OpenAI",
                available=True,
                models=list(OpenAIEmbeddingProvider.models.keys()),
            )
        )
    else:
        llm_providers.append(
            ProviderInfo(name="openai", label="OpenAI", available=False, error=openai_error)
        )
        embedding_providers.append(
            ProviderInfo(name="openai", label="OpenAI", available=False, error=openai_error)
        )

    # Check Anthropic
    anthropic_available, anthropic_error = check_anthropic_availability()
    if anthropic_available:
        llm_providers.append(
            ProviderInfo(
                name="anthropic",
                label="Anthropic",
                available=True,
                models=list(LLM_MODELS["anthropic"].keys()),
            )
        )
    else:
        llm_providers.append(
            ProviderInfo(
                name="anthropic", label="Anthropic", available=False, error=anthropic_error
            )
        )

    # Check Ollama - Read from DB config
    # We prefer the DB configured URL over the runtime factory/env var
    ollama_url = None
    try:
        from src.core.admin_ops.application.tuning_service import TuningService
        from src.core.database.session import async_session_maker

        tuning_service = TuningService(async_session_maker)
        # Assuming "default" tenant for now.
        config = await tuning_service.get_tenant_config("default")
        ollama_url = config.get("ollama_base_url")
    except Exception as e:
        logger.warning(f"Failed to fetch tenant config for Ollama URL: {e}")

    # Fallback to runtime factory if DB fetch fails or has no URL
    if not ollama_url:
        try:
            from src.core.generation.domain.ports.provider_factory import get_provider_factory

            factory = get_provider_factory()
            ollama_url = getattr(factory, "ollama_base_url", None)
        except Exception:
            pass

    (
        ollama_available,
        ollama_label,
        ollama_error,
        ollama_llm_models,
        ollama_embed_models,
    ) = await check_ollama_availability(base_url=ollama_url)
    llm_providers.append(
        ProviderInfo(
            name="ollama",
            label=ollama_label,
            available=ollama_available,
            error=ollama_error,
            models=ollama_llm_models if ollama_available else [],
        )
    )
    embedding_providers.append(
        ProviderInfo(
            name="ollama",
            label=ollama_label,
            available=ollama_available,
            error=ollama_error,
            models=ollama_embed_models if ollama_available else [],
        )
    )

    # Check Local Embeddings
    local_available, local_error = check_local_embeddings_availability()
    embedding_providers.append(
        ProviderInfo(
            name="local",
            label="Local (ONNX)",
            available=local_available,
            error=local_error,
            models=list(EMBEDDING_MODELS["local"].keys()) if local_available else [],
        )
    )

    return AvailableProvidersResponse(
        llm_providers=llm_providers, embedding_providers=embedding_providers
    )


@router.post("/validate", response_model=ValidateProviderResponse)
async def validate_provider(request: ValidateProviderRequest):
    """
    Validate a specific provider's connectivity.

    Used for retry functionality when a provider connection fails.
    """
    provider_name = request.provider_name.lower()
    provider_type = request.provider_type.lower()

    if provider_name == "openai":
        available, error = check_openai_availability()
        models = []
        if available:
            if provider_type == "llm":
                models = list(OpenAILLMProvider.models.keys())
            else:
                models = list(OpenAIEmbeddingProvider.models.keys())
        return ValidateProviderResponse(available=available, error=error, models=models)

    elif provider_name == "anthropic":
        available, error = check_anthropic_availability()
        models = list(LLM_MODELS["anthropic"].keys()) if available else []
        return ValidateProviderResponse(available=available, error=error, models=models)

    elif provider_name == "ollama":
        available, _, error, llm_models, embed_models = await check_ollama_availability()
        models = llm_models if provider_type == "llm" else embed_models
        return ValidateProviderResponse(available=available, error=error, models=models)

    elif provider_name == "local":
        available, error = check_local_embeddings_availability()
        models = list(EMBEDDING_MODELS["local"].keys()) if available else []
        return ValidateProviderResponse(available=available, error=error, models=models)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")


@router.post("/ollama/test-connection")
async def test_ollama_connection(request: OllamaTestRequest):
    """
    Test connectivity to a specific Ollama URL.

    Used by the admin UI to validate a URL before saving it.
    Returns connection status and available models.
    """
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    available, label, error, llm_models, embed_models = await check_ollama_availability(
        base_url=url
    )

    return {
        "available": available,
        "label": label,
        "error": error,
        "llm_models": llm_models,
        "embedding_models": embed_models,
    }
