"""
Tenant Configuration API
========================

Admin endpoints for managing tenant configuration and RAG tuning parameters.

Stage 10.2 - RAG Tuning Panel Backend
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.core.database.session import async_session_maker
from src.core.services.tuning import TuningService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["admin-config"])


# =============================================================================
# Schemas
# =============================================================================

class RetrievalWeights(BaseModel):
    """Retrieval fusion weights."""
    vector_weight: float = Field(0.35, ge=0, le=1, description="Vector search weight")
    graph_weight: float = Field(0.35, ge=0, le=1, description="Graph search weight")
    rerank_weight: float = Field(0.30, ge=0, le=1, description="Reranking influence")

    @field_validator('*', mode='after')
    @classmethod
    def validate_weights(cls, v):
        return round(v, 3)


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

    # Model settings
    embedding_model: str = "text-embedding-3-small"
    generation_model: str = "gpt-4o-mini"

    # Custom prompts
    system_prompt_override: str | None = None


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

    # Model settings
    embedding_model: str | None = None
    generation_model: str | None = None

    # Custom prompts
    system_prompt_override: str | None = None


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


class ConfigSchemaResponse(BaseModel):
    """Configuration schema for form generation."""
    fields: list[ConfigSchemaField]
    groups: list[str]


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/schema", response_model=ConfigSchemaResponse)
async def get_config_schema():
    """
    Get configuration schema for dynamic form generation.

    Returns field definitions with types, constraints, and groupings
    for rendering the tuning panel UI.
    """
    fields = [
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
            group="retrieval"
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
            group="retrieval"
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
            group="retrieval"
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
            group="weights"
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
            group="weights"
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
            group="weights"
        ),

        # Feature Toggles
        ConfigSchemaField(
            name="reranking_enabled",
            type="boolean",
            label="Enable Reranking",
            description="Use cross-encoder reranking for better precision",
            default=True,
            group="features"
        ),
        ConfigSchemaField(
            name="hyde_enabled",
            type="boolean",
            label="Enable HyDE",
            description="Generate hypothetical documents for retrieval",
            default=False,
            group="features"
        ),
        ConfigSchemaField(
            name="graph_expansion_enabled",
            type="boolean",
            label="Enable Graph Expansion",
            description="Expand results using knowledge graph relationships",
            default=True,
            group="features"
        ),

        # Model Settings
        ConfigSchemaField(
            name="embedding_model",
            type="select",
            label="Embedding Model",
            description="Model for generating embeddings",
            default="text-embedding-3-small",
            options=[
                "text-embedding-3-small",
                "text-embedding-3-large",
                "voyage-3.5-lite",
                "bge-m3"
            ],
            group="models"
        ),
        ConfigSchemaField(
            name="generation_model",
            type="select",
            label="Generation Model",
            description="LLM for answer generation",
            default="gpt-4o-mini",
            options=[
                "gpt-4o-mini",
                "gpt-4o",
                "claude-sonnet-4-20250514",
                "claude-3-5-haiku-20241022"
            ],
            group="models"
        ),

        # Custom Prompts
        ConfigSchemaField(
            name="system_prompt_override",
            type="string",
            label="System Prompt Override",
            description="Custom system prompt for answer generation (leave empty for default)",
            default="",
            group="prompts"
        ),
    ]

    return ConfigSchemaResponse(
        fields=fields,
        groups=["retrieval", "weights", "features", "models", "prompts"]
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
            embedding_model=config.get("embedding_model", "text-embedding-3-small"),
            generation_model=config.get("generation_model", "gpt-4o-mini"),
            system_prompt_override=config.get("system_prompt_override"),
        )

    except Exception as e:
        logger.error(f"Failed to get tenant config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get config: {str(e)}") from e


@router.put("/tenants/{tenant_id}", response_model=TenantConfigResponse)
async def update_tenant_config(tenant_id: str, update: TenantConfigUpdate):
    """
    Update configuration for a specific tenant.

    Only provided fields are updated; others remain unchanged.
    Changes take effect immediately for subsequent requests.
    """
    try:
        from sqlalchemy.future import select

        from src.core.models.tenant import Tenant

        async with async_session_maker() as session:
            result = await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            tenant = result.scalar_one_or_none()

            if not tenant:
                raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

            # Initialize config if needed
            if not tenant.config:
                tenant.config = {}

            # Update provided fields
            update_dict = update.model_dump(exclude_unset=True, exclude_none=True)

            # Handle nested weights
            if "weights" in update_dict:
                weights = update_dict.pop("weights")
                for k, v in weights.items():
                    tenant.config[k] = v

            # Update remaining fields
            for key, value in update_dict.items():
                tenant.config[key] = value

            # Persist changes
            session.add(tenant)
            await session.commit()

            # Log the change
            tuning_service = TuningService(async_session_maker)
            await tuning_service.log_change(
                tenant_id=tenant_id,
                actor="admin",  # TODO: Get from auth context
                action="update_config",
                target_type="tenant",
                target_id=tenant_id,
                changes=update_dict
            )

            logger.info(f"Updated config for tenant {tenant_id}: {update_dict.keys()}")

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

        from src.core.models.tenant import Tenant

        async with async_session_maker() as session:
            result = await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
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
                changes={"old_config": old_config}
            )

            logger.info(f"Reset config for tenant {tenant_id}")

        return {"status": "success", "message": f"Configuration reset for tenant {tenant_id}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset tenant config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset config: {str(e)}") from e
