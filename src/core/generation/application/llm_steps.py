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
    "ingestion.entity_summarization": LLMStepDef(
        id="ingestion.entity_summarization",
        label="Entity Summarization",
        feature="ingestion",
        description="Consolidate entity descriptions",
        temperature_strategy="fixed",
        seed_strategy="provider",
        default_temperature=0.3,
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
    
    # DEBUG
    print(f"DEBUG: resolve_llm_step_config | step={step_id} | tenant_provider={tenant_config.get('llm_provider')}")

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
