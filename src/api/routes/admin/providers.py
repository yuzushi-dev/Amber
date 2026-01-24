"""
Provider Discovery API
======================

Admin endpoints for discovering available LLM and embedding providers.
Returns only providers with valid configuration and their available models.
"""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["admin-providers"])


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


# =============================================================================
# Helper Functions
# =============================================================================


async def check_ollama_availability() -> tuple[bool, str | None, list[str], list[str]]:
    """
    Check if Ollama is available and list installed models.
    
    Returns:
        (available, error_message, llm_models, embedding_models)
    """
    base_url = settings.ollama_base_url.rstrip("/v1")  # Remove /v1 for native API
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url}/api/tags")
            
            if response.status_code != 200:
                return False, f"Ollama returned status {response.status_code}", [], []
            
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
            
            return True, None, llm_models, embedding_models
            
    except httpx.ConnectError:
        return False, f"Cannot connect to Ollama at {base_url}", [], []
    except httpx.TimeoutException:
        return False, "Ollama connection timed out", [], []
    except Exception as e:
        return False, str(e), [], []


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
    try:
        from src.core.generation.infrastructure.providers.local import LocalEmbeddingProvider
        return True, None
    except ImportError as e:
        return False, f"Local embeddings not available: {e}"


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
        llm_providers.append(ProviderInfo(
            name="openai",
            label="OpenAI",
            available=True,
            models=["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]
        ))
        embedding_providers.append(ProviderInfo(
            name="openai",
            label="OpenAI",
            available=True,
            models=["text-embedding-3-small", "text-embedding-3-large"]
        ))
    else:
        llm_providers.append(ProviderInfo(
            name="openai",
            label="OpenAI",
            available=False,
            error=openai_error
        ))
        embedding_providers.append(ProviderInfo(
            name="openai",
            label="OpenAI",
            available=False,
            error=openai_error
        ))
    
    # Check Anthropic
    anthropic_available, anthropic_error = check_anthropic_availability()
    if anthropic_available:
        llm_providers.append(ProviderInfo(
            name="anthropic",
            label="Anthropic",
            available=True,
            models=["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]
        ))
    else:
        llm_providers.append(ProviderInfo(
            name="anthropic",
            label="Anthropic",
            available=False,
            error=anthropic_error
        ))
    
    # Check Ollama
    ollama_available, ollama_error, ollama_llm_models, ollama_embed_models = await check_ollama_availability()
    llm_providers.append(ProviderInfo(
        name="ollama",
        label="Ollama (Local)",
        available=ollama_available,
        error=ollama_error,
        models=ollama_llm_models if ollama_available else []
    ))
    embedding_providers.append(ProviderInfo(
        name="ollama",
        label="Ollama (Local)",
        available=ollama_available,
        error=ollama_error,
        models=ollama_embed_models if ollama_available else []
    ))
    
    # Check Local Embeddings
    local_available, local_error = check_local_embeddings_availability()
    embedding_providers.append(ProviderInfo(
        name="local",
        label="Local (ONNX)",
        available=local_available,
        error=local_error,
        models=["bge-m3"] if local_available else []
    ))
    
    return AvailableProvidersResponse(
        llm_providers=llm_providers,
        embedding_providers=embedding_providers
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
                models = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]
            else:
                models = ["text-embedding-3-small", "text-embedding-3-large"]
        return ValidateProviderResponse(available=available, error=error, models=models)
    
    elif provider_name == "anthropic":
        available, error = check_anthropic_availability()
        models = ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"] if available else []
        return ValidateProviderResponse(available=available, error=error, models=models)
    
    elif provider_name == "ollama":
        available, error, llm_models, embed_models = await check_ollama_availability()
        models = llm_models if provider_type == "llm" else embed_models
        return ValidateProviderResponse(available=available, error=error, models=models)
    
    elif provider_name == "local":
        available, error = check_local_embeddings_availability()
        models = ["bge-m3"] if available else []
        return ValidateProviderResponse(available=available, error=error, models=models)
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")
