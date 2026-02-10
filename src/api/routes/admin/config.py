"""
Tenant Configuration API
========================

Admin endpoints for managing tenant configuration and RAG tuning parameters.

Stage 10.2 - RAG Tuning Panel Backend
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.api.config import settings
from src.api.deps import verify_super_admin
from src.core.admin_ops.application.tuning_service import TuningService
from src.core.database.session import async_session_maker
from src.core.tenants.application.active_vector_collection import (
    backfill_active_vector_collections,
    ensure_active_collection_update_allowed,
)
from src.shared.model_registry import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LLM_MODEL,
    EMBEDDING_MODELS,
    LLM_MODELS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["admin-config"])


# =============================================================================
# Schemas
# =============================================================================


def _resolve_default_llm_model() -> str:
    if settings.default_llm_model:
        return settings.default_llm_model
    provider = settings.default_llm_provider or "openai"
    fallback = DEFAULT_LLM_MODEL.get(provider)
    if not fallback:
        fallback = next(iter(LLM_MODELS.get(provider, {})), None)
    return fallback or DEFAULT_LLM_MODEL.get("openai", "")


def _resolve_default_embedding_model() -> str:
    if settings.default_embedding_model:
        return settings.default_embedding_model
    provider = settings.default_embedding_provider or "openai"
    fallback = DEFAULT_EMBEDDING_MODEL.get(provider)
    if not fallback:
        fallback = next(iter(EMBEDDING_MODELS.get(provider, {})), None)
    return fallback or DEFAULT_EMBEDDING_MODEL.get("openai", "")


class RetrievalWeights(BaseModel):
    """Retrieval fusion weights."""

    vector_weight: float = Field(0.35, ge=0, le=1, description="Vector search weight")
    graph_weight: float = Field(0.35, ge=0, le=1, description="Graph search weight")
    rerank_weight: float = Field(0.30, ge=0, le=1, description="Reranking influence")

    @field_validator("*", mode="after")
    @classmethod
    def validate_weights(cls, v):
        return round(v, 3)


class LLMStepOverride(BaseModel):
    """Per-step LLM override settings."""

    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    seed: int | None = None


class TenantConfigResponse(BaseModel):
    """Tenant configuration response."""

    tenant_id: str
    config: dict[str, Any]
    weights: RetrievalWeights | None = None

    # RAG Parameters
    top_k: int = Field(10, ge=1, le=100)
    expansion_depth: int = Field(2, ge=1, le=5)
    similarity_threshold: float = Field(0.7, ge=0, le=1)

    # Feature toggles
    reranking_enabled: bool = True
    hyde_enabled: bool = False
    graph_expansion_enabled: bool = True

    # LLM Provider/Model settings
    llm_provider: str = Field(default_factory=lambda: settings.default_llm_provider or "openai")
    llm_model: str = Field(default_factory=_resolve_default_llm_model)

    # Embedding Provider/Model settings
    embedding_provider: str = Field(
        default_factory=lambda: settings.default_embedding_provider or "openai"
    )
    embedding_model: str = Field(default_factory=_resolve_default_embedding_model)

    # Vector Store Settings
    active_vector_collection: str | None = None

    # Ollama Connection
    ollama_base_url: str | None = None

    # Determinism Settings
    seed: int | None = None
    temperature: float | None = None
    llm_steps: dict[str, "LLMStepOverride"] | None = None

    # Custom prompts (per-tenant overrides)
    rag_system_prompt: str | None = None
    rag_user_prompt: str | None = None
    agent_system_prompt: str | None = None
    community_summary_prompt: str | None = None
    fact_extraction_prompt: str | None = None

    # Ingestion Settings
    hybrid_ocr_enabled: bool = True
    ocr_text_density_threshold: int = 50


class TenantConfigUpdate(BaseModel):
    """Tenant configuration update request."""

    # RAG Parameters
    top_k: int | None = Field(None, ge=1, le=100)
    expansion_depth: int | None = Field(None, ge=1, le=5)
    similarity_threshold: float | None = Field(None, ge=0, le=1)

    # Weights
    weights: RetrievalWeights | None = None

    # Feature toggles
    reranking_enabled: bool | None = None
    hyde_enabled: bool | None = None
    graph_expansion_enabled: bool | None = None

    # LLM Provider/Model settings
    llm_provider: str | None = None
    llm_model: str | None = None

    # Embedding Provider/Model settings
    embedding_provider: str | None = None
    embedding_model: str | None = None

    # Vector Store Settings
    active_vector_collection: str | None = None

    # Ollama Connection
    ollama_base_url: str | None = None

    # Determinism Settings
    seed: int | None = None
    temperature: float | None = None
    llm_steps: dict[str, "LLMStepOverride"] | None = None

    # Custom prompts (per-tenant overrides)
    rag_system_prompt: str | None = None
    rag_user_prompt: str | None = None
    agent_system_prompt: str | None = None
    community_summary_prompt: str | None = None
    fact_extraction_prompt: str | None = None

    # Ingestion Settings
    hybrid_ocr_enabled: bool | None = None
    ocr_text_density_threshold: int | None = Field(None, ge=0, le=1000)


class ConfigSchemaField(BaseModel):
    """Schema field definition for UI rendering."""

    name: str
    type: str  # 'number', 'boolean', 'string', 'select'
    label: str
    description: str
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None
    group: str = "general"
    read_only: bool = False


class ConfigSchemaResponse(BaseModel):
    """Configuration schema for form generation."""

    fields: list[ConfigSchemaField]
    groups: list[str]


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/llm-steps")
async def get_llm_steps():
    """
    Return LLM step metadata for UI configuration.
    """
    from src.core.generation.application.llm_steps import LLM_STEP_DEFS

    steps = [
        {
            "id": step.id,
            "label": step.label,
            "feature": step.feature,
            "description": step.description,
            "default_temperature": step.default_temperature,
            "default_seed": step.default_seed,
        }
        for step in LLM_STEP_DEFS.values()
    ]

    return {"steps": steps}


@router.get("/schema", response_model=ConfigSchemaResponse)
async def get_config_schema():
    """
    Get configuration schema for dynamic form generation.

    Returns field definitions with types, constraints, and groupings
    for rendering the tuning panel UI.
    """
    fields = [
        # Ingestion Settings
        ConfigSchemaField(
            name="hybrid_ocr_enabled",
            type="boolean",
            label="Enable Hybrid OCR",
            description="Use OCR only for image-heavy pages (slower but more accurate)",
            default=True,
            group="ingestion",
        ),
        ConfigSchemaField(
            name="ocr_text_density_threshold",
            type="number",
            label="OCR Trigger Threshold",
            description="Minimum character count per page to avoid OCR (lower triggers OCR)",
            default=50,
            min=0,
            max=1000,
            step=10,
            group="ingestion",
        ),
        # Model Settings - Provider Selection
        ConfigSchemaField(
            name="llm_provider",
            type="select",
            label="LLM Provider",
            description="Provider for answer generation (models loaded dynamically)",
            default=settings.default_llm_provider or "openai",
            options=[],  # Populated dynamically by frontend from /admin/providers/available
            group="models",
        ),
        ConfigSchemaField(
            name="llm_model",
            type="select",
            label="LLM Model",
            description="Model for answer generation",
            default=_resolve_default_llm_model(),
            options=[],  # Populated dynamically based on selected provider
            group="models",
        ),
        ConfigSchemaField(
            name="embedding_provider",
            type="select",
            label="Embedding Provider",
            description="Provider for vector embeddings (models loaded dynamically)",
            default=settings.default_embedding_provider or "openai",
            options=[],  # Populated dynamically by frontend
            group="models",
        ),
        ConfigSchemaField(
            name="embedding_model",
            type="select",
            label="Embedding Model",
            description="Model for generating embeddings",
            default=_resolve_default_embedding_model(),
            options=[],  # Populated dynamically based on selected provider
            group="models",
        ),
        # Model Parameters (Determinism)
        ConfigSchemaField(
            name="temperature",
            type="number",
            label="Temperature",
            description="Controls randomness (0.0 = deterministic, 1.0 = creative)",
            default=settings.default_llm_temperature,
            min=0.0,
            max=2.0,
            step=0.1,
            group="models",
        ),
        ConfigSchemaField(
            name="seed",
            type="number",
            label="Random Seed",
            description="Fixed integer for reproducible outputs (best effort)",
            default=settings.seed,  # Show global default in UI
            group="models",
        ),
        # Feature Toggles
        ConfigSchemaField(
            name="reranking_enabled",
            type="boolean",
            label="Enable Reranking",
            description="Use cross-encoder reranking for better precision",
            default=True,
            group="features",
        ),
        ConfigSchemaField(
            name="hyde_enabled",
            type="boolean",
            label="Enable HyDE",
            description="Generate hypothetical documents for retrieval",
            default=False,
            group="features",
        ),
        ConfigSchemaField(
            name="graph_expansion_enabled",
            type="boolean",
            label="Enable Graph Expansion",
            description="Expand results using knowledge graph relationships",
            default=True,
            group="features",
        ),
        # Retrieval Parameters
        ConfigSchemaField(
            name="top_k",
            type="number",
            label="Top K Results",
            description="Number of chunks to retrieve before reranking",
            default=10,
            min=1,
            max=100,
            step=1,
            group="retrieval",
        ),
        ConfigSchemaField(
            name="active_vector_collection",
            type="string",
            label="Active Vector Collection",
            description="Milvus collection used for retrieval and ingestion for this tenant",
            default="amber_default",
            group="retrieval",
        ),
        ConfigSchemaField(
            name="expansion_depth",
            type="number",
            label="Graph Expansion Depth",
            description="How many hops to traverse in the knowledge graph",
            default=2,
            min=1,
            max=5,
            step=1,
            group="retrieval",
        ),
        ConfigSchemaField(
            name="similarity_threshold",
            type="number",
            label="Similarity Threshold",
            description="Minimum similarity score for including results",
            default=0.7,
            min=0,
            max=1,
            step=0.05,
            group="retrieval",
        ),
        # Weights
        ConfigSchemaField(
            name="vector_weight",
            type="number",
            label="Vector Search Weight",
            description="Weight for vector similarity in fusion",
            default=0.35,
            min=0,
            max=1,
            step=0.05,
            group="weights",
        ),
        ConfigSchemaField(
            name="graph_weight",
            type="number",
            label="Graph Search Weight",
            description="Weight for graph-based results in fusion",
            default=0.35,
            min=0,
            max=1,
            step=0.05,
            group="weights",
        ),
        ConfigSchemaField(
            name="rerank_weight",
            type="number",
            label="Rerank Weight",
            description="Influence of reranking on final scores",
            default=0.30,
            min=0,
            max=1,
            step=0.05,
            group="weights",
        ),
        # Custom Prompts
        ConfigSchemaField(
            name="rag_system_prompt",
            type="string",
            label="RAG System Prompt",
            description="System instructions for answer generation. Controls tone, citation style, and grounding behavior.",
            default="",
            group="prompts",
        ),
        ConfigSchemaField(
            name="rag_user_prompt",
            type="string",
            label="RAG User Prompt Template",
            description="Template for formatting context and query. Use {context}, {memory_context}, {query} placeholders.",
            default="",
            group="prompts",
        ),
        ConfigSchemaField(
            name="agent_system_prompt",
            type="string",
            label="Agent System Prompt",
            description="Instructions for agentic mode with tool usage. Defines available tools and decision-making behavior.",
            default="",
            group="prompts",
        ),
        ConfigSchemaField(
            name="community_summary_prompt",
            type="string",
            label="Community Summary Prompt",
            description="Prompt for generating knowledge graph community reports.",
            default="",
            group="prompts",
        ),
        ConfigSchemaField(
            name="fact_extraction_prompt",
            type="string",
            label="Fact Extraction Prompt",
            description="Instructions for extracting memory facts from user conversations.",
            default="",
            group="prompts",
        ),
    ]

    return ConfigSchemaResponse(
        fields=fields, groups=["ingestion", "models", "features", "retrieval", "weights", "prompts"]
    )


class DefaultPromptsResponse(BaseModel):
    """Default prompt templates."""

    rag_system_prompt: str
    rag_user_prompt: str
    agent_system_prompt: str
    community_summary_prompt: str
    fact_extraction_prompt: str


@router.get("/prompts/defaults", response_model=DefaultPromptsResponse)
async def get_default_prompts():
    """
    Get default prompt templates.

    Returns all built-in prompts that are used when no tenant override is set.
    These serve as the baseline/fallback for all prompt fields.
    """
    from src.core.generation.application.agent.prompts import AGENT_SYSTEM_PROMPT
    from src.core.generation.application.prompts.community_summary import (
        COMMUNITY_SUMMARY_SYSTEM_PROMPT,
    )
    from src.core.generation.application.prompts.templates import FACT_EXTRACTION_PROMPT, PROMPTS

    return DefaultPromptsResponse(
        rag_system_prompt=PROMPTS["rag_system"]["latest"],
        rag_user_prompt=PROMPTS["rag_user"]["latest"],
        agent_system_prompt=AGENT_SYSTEM_PROMPT,
        community_summary_prompt=COMMUNITY_SUMMARY_SYSTEM_PROMPT,
        fact_extraction_prompt=FACT_EXTRACTION_PROMPT,
    )


@router.get("/tenants/{tenant_id}", response_model=TenantConfigResponse)
async def get_tenant_config(tenant_id: str):
    """
    Get configuration for a specific tenant.

    Returns all tunable parameters and their current values.
    """
    try:
        tuning_service = TuningService(async_session_maker)
        config = await tuning_service.get_tenant_config(tenant_id)

        # Extract weights if present
        weights = None
        if any(k.endswith("_weight") for k in config):
            weights = RetrievalWeights(
                vector_weight=config.get("vector_weight", 0.35),
                graph_weight=config.get("graph_weight", 0.35),
                rerank_weight=config.get("rerank_weight", 0.30),
            )

        from src.core.generation.application.llm_model_resolver import resolve_tenant_llm_model

        resolved_model, _ = resolve_tenant_llm_model(
            config,
            settings,
            context="admin.config_response",
            tenant_id=tenant_id,
        )

        return TenantConfigResponse(
            tenant_id=tenant_id,
            config=config,
            weights=weights,
            top_k=config.get("top_k", 10),
            expansion_depth=config.get("expansion_depth", 2),
            similarity_threshold=config.get("similarity_threshold", 0.7),
            reranking_enabled=config.get("reranking_enabled", True),
            hyde_enabled=config.get("hyde_enabled", False),
            graph_expansion_enabled=config.get("graph_expansion_enabled", True),
            llm_provider=config.get("llm_provider", settings.default_llm_provider or "openai"),
            llm_model=resolved_model or _resolve_default_llm_model(),
            embedding_provider=config.get(
                "embedding_provider", settings.default_embedding_provider or "openai"
            ),
            embedding_model=config.get("embedding_model", _resolve_default_embedding_model()),
            active_vector_collection=config.get("active_vector_collection"),
            ollama_base_url=config.get("ollama_base_url", settings.ollama_base_url),
            seed=config.get("seed"),
            temperature=config.get("temperature"),
            llm_steps=config.get("llm_steps"),
            # Prompt overrides (per-tenant)
            rag_system_prompt=config.get("rag_system_prompt"),
            rag_user_prompt=config.get("rag_user_prompt"),
            agent_system_prompt=config.get("agent_system_prompt"),
            community_summary_prompt=config.get("community_summary_prompt"),
            fact_extraction_prompt=config.get("fact_extraction_prompt"),
            hybrid_ocr_enabled=config.get("hybrid_ocr_enabled", True),
            ocr_text_density_threshold=config.get("ocr_text_density_threshold", 50),
        )

    except Exception as e:
        logger.error(f"Failed to get tenant config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get config: {str(e)}") from e


@router.put("/tenants/{tenant_id}", response_model=TenantConfigResponse)
async def update_tenant_config(tenant_id: str, update: TenantConfigUpdate, request: Request):
    """
    Update configuration for a specific tenant.

    Only provided fields are updated; others remain unchanged.
    Changes take effect immediately for subsequent requests.
    """
    try:
        update_dict = update.model_dump(exclude_unset=True, exclude_none=True)
        try:
            ensure_active_collection_update_allowed(
                getattr(request.state, "is_super_admin", False),
                update_dict,
            )
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

        llm_keys = {"llm_provider", "llm_model", "temperature", "seed", "llm_steps", "ollama_base_url"}
        llm_update = {key: value for key, value in update_dict.items() if key in llm_keys}
        other_update = {key: value for key, value in update_dict.items() if key not in llm_keys}
        is_super_admin = getattr(request.state, "is_super_admin", False)

        if llm_update and not is_super_admin:
            raise HTTPException(status_code=403, detail="Super Admin privileges required")

        from sqlalchemy.future import select

        from src.core.tenants.domain.tenant import Tenant

        def apply_config_updates(tenant: Tenant, updates: dict[str, Any]) -> None:
            if not tenant.config:
                tenant.config = {}

            new_config = dict(tenant.config)
            weights = updates.get("weights")
            if weights:
                for k, v in weights.items():
                    new_config[k] = v

            for key, value in updates.items():
                if key == "weights":
                    continue
                new_config[key] = value
                if key == "llm_model":
                    new_config["generation_model"] = value

            tenant.config = new_config

        async with async_session_maker() as session:
            if is_super_admin and llm_update:
                result = await session.execute(select(Tenant))
                tenants = result.scalars().all()
                target_tenant = next((tenant for tenant in tenants if tenant.id == tenant_id), None)

                if not target_tenant:
                    raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

                for tenant in tenants:
                    apply_config_updates(tenant, llm_update)
                    session.add(tenant)

                if other_update:
                    apply_config_updates(target_tenant, other_update)
                    session.add(target_tenant)

                await session.commit()

                tuning_service = TuningService(async_session_maker)
                for tenant in tenants:
                    await tuning_service.log_change(
                        tenant_id=tenant.id,
                        actor="admin",  # TODO: Get from auth context
                        action="update_config",
                        target_type="tenant",
                        target_id=tenant.id,
                        changes=llm_update,
                    )

                if other_update:
                    await tuning_service.log_change(
                        tenant_id=tenant_id,
                        actor="admin",
                        action="update_config",
                        target_type="tenant",
                        target_id=tenant_id,
                        changes=other_update,
                    )

                logger.info("Updated LLM config for all tenants: %s", list(llm_update.keys()))
            else:
                result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
                tenant = result.scalar_one_or_none()

                if not tenant:
                    raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

                apply_config_updates(tenant, update_dict)

                session.add(tenant)
                await session.commit()

                tuning_service = TuningService(async_session_maker)
                await tuning_service.log_change(
                    tenant_id=tenant_id,
                    actor="admin",  # TODO: Get from auth context
                    action="update_config",
                    target_type="tenant",
                    target_id=tenant_id,
                    changes=update_dict,
                )

                logger.info(f"Updated config for tenant {tenant_id}: {update_dict.keys()}")

        # Propagate ollama_base_url change to running factory
        if "ollama_base_url" in update_dict:
            try:
                from src.core.generation.domain.ports.provider_factory import (
                    get_provider_factory,
                )

                factory = get_provider_factory()
                factory.update_ollama_base_url(update_dict["ollama_base_url"])
                logger.info(
                    "Updated running factory ollama_base_url to: %s",
                    update_dict["ollama_base_url"],
                )
            except Exception as e:
                logger.warning(f"Failed to update running factory ollama_base_url: {e}")

        # Return updated config
        return await get_tenant_config(tenant_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update tenant config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}") from e


@router.post("/tenants/{tenant_id}/reset")
async def reset_tenant_config(tenant_id: str):
    """
    Reset tenant configuration to defaults.

    Removes all custom configuration, reverting to system defaults.
    """
    try:
        from sqlalchemy.future import select

        from src.core.tenants.domain.tenant import Tenant

        async with async_session_maker() as session:
            result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = result.scalar_one_or_none()

            if not tenant:
                raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

            # Store old config for audit
            old_config = dict(tenant.config) if tenant.config else {}

            # Reset to empty
            tenant.config = {}
            session.add(tenant)
            await session.commit()

            # Log the reset
            tuning_service = TuningService(async_session_maker)
            await tuning_service.log_change(
                tenant_id=tenant_id,
                actor="admin",
                action="reset_config",
                target_type="tenant",
                target_id=tenant_id,
                changes={"old_config": old_config},
            )

            logger.info(f"Reset config for tenant {tenant_id}")

        return {"status": "success", "message": f"Configuration reset for tenant {tenant_id}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset tenant config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset config: {str(e)}") from e


@router.post("/tenants/backfill-active-collection", dependencies=[Depends(verify_super_admin)])
async def backfill_active_vector_collection():
    """
    Backfill active_vector_collection for tenants missing the setting.
    Super Admin only.
    """
    try:
        from sqlalchemy.future import select

        from src.core.tenants.domain.tenant import Tenant

        async with async_session_maker() as session:
            result = await session.execute(select(Tenant))
            tenants = result.scalars().all()
            updated = backfill_active_vector_collections(tenants)
            await session.commit()

        return {"updated": updated, "total": len(tenants)}
    except Exception as e:
        logger.error(f"Failed to backfill active collections: {e}")
        raise HTTPException(status_code=500, detail=f"Backfill failed: {str(e)}") from e
