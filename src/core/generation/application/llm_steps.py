from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TemperatureStrategy = Literal["fixed", "tenant", "settings", "provider"]
SeedStrategy = Literal["fixed", "tenant", "settings", "provider"]


@dataclass(frozen=True)
class LLMStepConfig:
    provider: str | None
    model: str | None
    temperature: float | None
    seed: int | None


@dataclass(frozen=True)
class LLMStepDef:
    id: str
    label: str
    feature: str
    description: str
    temperature_strategy: TemperatureStrategy
    seed_strategy: SeedStrategy
    default_temperature: float | None = None
    default_seed: int | None = None


LLM_STEP_DEFS: dict[str, LLMStepDef] = {
    # Ingestion
    "ingestion.graph_extraction": LLMStepDef(
        id="ingestion.graph_extraction",
        label="Graph Extraction",
        feature="ingestion",
        description="Extract entities and relationships from chunks",
        temperature_strategy="fixed",
        seed_strategy="settings",
        default_temperature=0.0,
    ),
    "ingestion.document_summarization": LLMStepDef(
        id="ingestion.document_summarization",
        label="Document Summarization",
        feature="ingestion",
        description="Summarize document content and classify metadata",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.3,
    ),
    "ingestion.chunk_context": LLMStepDef(
        id="ingestion.chunk_context",
        label="Chunk Contextualization",
        feature="ingestion",
        description="Generate a short situating context for each chunk (contextual retrieval)",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.0,
    ),
    # Graph
    "graph.community_summary": LLMStepDef(
        id="graph.community_summary",
        label="Community Summary",
        feature="graph",
        description="Summarize graph communities",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.3,
    ),
    # Retrieval helpers
    "retrieval.query_router": LLMStepDef(
        id="retrieval.query_router",
        label="Query Router",
        feature="retrieval",
        description="Route queries to a search mode",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    "retrieval.query_rewrite": LLMStepDef(
        id="retrieval.query_rewrite",
        label="Query Rewrite",
        feature="retrieval",
        description="Rewrite queries using conversation context",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    "retrieval.query_decompose": LLMStepDef(
        id="retrieval.query_decompose",
        label="Query Decompose",
        feature="retrieval",
        description="Split complex queries into sub-queries",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    "retrieval.hyde_generation": LLMStepDef(
        id="retrieval.hyde_generation",
        label="HyDE Generation",
        feature="retrieval",
        description="Generate hypothetical answers for retrieval",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    "retrieval.sufficiency_check": LLMStepDef(
        id="retrieval.sufficiency_check",
        label="Sufficiency Check",
        feature="retrieval",
        description="Judge whether retrieved context is sufficient and propose gap queries",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.0,
    ),
    "retrieval.global_map": LLMStepDef(
        id="retrieval.global_map",
        label="Global Search Map",
        feature="retrieval",
        description="Map phase for global search",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    "retrieval.global_reduce": LLMStepDef(
        id="retrieval.global_reduce",
        label="Global Search Reduce",
        feature="retrieval",
        description="Reduce phase for global search",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    "retrieval.drift_followups": LLMStepDef(
        id="retrieval.drift_followups",
        label="Drift Follow-ups",
        feature="retrieval",
        description="Generate follow-up questions for DRIFT",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    "retrieval.drift_synthesis": LLMStepDef(
        id="retrieval.drift_synthesis",
        label="Drift Synthesis",
        feature="retrieval",
        description="Synthesize DRIFT final answer",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    # Chat / generation
    "chat.generation": LLMStepDef(
        id="chat.generation",
        label="Chat Generation",
        feature="chat",
        description="Generate grounded chat answers",
        temperature_strategy="fixed",
        seed_strategy="tenant",
        default_temperature=0.1,
    ),
    "chat.agent_completion": LLMStepDef(
        id="chat.agent_completion",
        label="Agent Completion",
        feature="chat",
        description="Agentic chat completion with tools",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.1,
    ),
    # Memory
    "memory.fact_extraction": LLMStepDef(
        id="memory.fact_extraction",
        label="Fact Extraction",
        feature="memory",
        description="Extract user facts from queries",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.0,
    ),
    "memory.conversation_summary": LLMStepDef(
        id="memory.conversation_summary",
        label="Conversation Summary",
        feature="memory",
        description="Summarize conversation history",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.1,
    ),
    # Admin / evaluation
    "admin.quality_scorer": LLMStepDef(
        id="admin.quality_scorer",
        label="Quality Scorer",
        feature="admin",
        description="LLM scoring for quality metrics",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.0,
    ),
    "admin.judge_faithfulness": LLMStepDef(
        id="admin.judge_faithfulness",
        label="Judge Faithfulness",
        feature="admin",
        description="LLM judge for faithfulness",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.0,
    ),
    "admin.judge_relevance": LLMStepDef(
        id="admin.judge_relevance",
        label="Judge Relevance",
        feature="admin",
        description="LLM judge for relevance",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.0,
    ),
    "admin.feedback_analysis": LLMStepDef(
        id="admin.feedback_analysis",
        label="Feedback Analysis",
        feature="admin",
        description="Analyze feedback for tuning",
        temperature_strategy="provider",
        seed_strategy="provider",
    ),
    "admin.ragas_fallback": LLMStepDef(
        id="admin.ragas_fallback",
        label="RAGAS Fallback",
        feature="admin",
        description="Judge fallback used by RAGAS",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.0,
    ),
}


def _resolve_temperature(
    step: LLMStepDef,
    tenant_config: dict[str, Any],
    settings: Any,
) -> float | None:
    if step.temperature_strategy == "fixed":
        return step.default_temperature
    if step.temperature_strategy == "tenant":
        return tenant_config.get("temperature", settings.default_llm_temperature)
    if step.temperature_strategy == "settings":
        return settings.default_llm_temperature
    if step.temperature_strategy == "provider":
        return None
    return None


def _resolve_seed(
    step: LLMStepDef,
    tenant_config: dict[str, Any],
    settings: Any,
) -> int | None:
    if step.seed_strategy == "fixed":
        return step.default_seed
    if step.seed_strategy == "tenant":
        return tenant_config.get("seed", settings.seed)
    if step.seed_strategy == "settings":
        return settings.seed
    if step.seed_strategy == "provider":
        return None
    return None


def resolve_llm_step_config(
    *,
    tenant_config: dict[str, Any],
    step_id: str,
    settings: Any,
) -> LLMStepConfig:
    step = LLM_STEP_DEFS[step_id]
    step_overrides = (tenant_config.get("llm_steps") or {}).get(step_id, {})

    provider = (
        step_overrides.get("provider")
        or tenant_config.get("llm_provider")
        or settings.default_llm_provider
    )
    model = step_overrides.get("model")
    if model is None:
        from src.core.generation.application.llm_model_resolver import resolve_tenant_llm_model

        model, _ = resolve_tenant_llm_model(
            tenant_config,
            settings,
            context="llm_steps",
            step_id=step_id,
        )

    temperature = step_overrides.get("temperature")
    if temperature is None:
        temperature = _resolve_temperature(step, tenant_config, settings)

    seed = step_overrides.get("seed")
    if seed is None:
        seed = _resolve_seed(step, tenant_config, settings)

    return LLMStepConfig(
        provider=provider,
        model=model,
        temperature=temperature,
        seed=seed,
    )


def validate_llm_step_override(provider: str | None, model: str | None) -> str | None:
    """Return an error message if the provider/model override isn't known to
    src.shared.model_registry, else None. Both being None (unset override)
    is always valid -- nothing to check. `model` given alone (no explicit
    provider -- e.g. a CLI/API caller overriding only the model of an
    existing step) is checked against ALL known providers, since the
    effective provider it will end up paired with is resolved elsewhere
    (tenant_config/settings) and isn't visible here -- see callers for why
    this alone isn't sufficient and the caller must also validate the
    fully-merged (provider, model) pair it's about to persist.
    """
    if provider is None and model is None:
        return None

    from src.shared.model_registry import LLM_MODEL_TO_PROVIDERS, LLM_MODELS

    if provider is None:
        if model not in LLM_MODEL_TO_PROVIDERS:
            return f"Unknown model '{model}': not found for any configured provider."
        return None

    provider_models = LLM_MODELS.get(provider)
    if provider_models is None:
        known_providers = ", ".join(sorted(LLM_MODELS))
        return f"Unknown LLM provider '{provider}'. Known providers: {known_providers}."

    if model is not None and model not in provider_models:
        known_models = ", ".join(sorted(provider_models))
        return (
            f"Unknown model '{model}' for provider '{provider}'. "
            f"Known models for '{provider}': {known_models}."
        )

    return None
