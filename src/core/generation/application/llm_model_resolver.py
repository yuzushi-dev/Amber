import logging
from typing import Any, Literal

LLMModelSource = Literal["llm_model", "generation_model", "settings_default", "missing"]

_logger = logging.getLogger(__name__)
_logged_generation_fallback: set[tuple[str | None, str]] = set()


def _normalize_model(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def resolve_tenant_llm_model(
    tenant_config: dict[str, Any],
    settings: Any,
    *,
    context: str,
    tenant_id: str | None = None,
    step_id: str | None = None,
) -> tuple[str | None, LLMModelSource]:
    llm_model = _normalize_model(tenant_config.get("llm_model"))
    if llm_model:
        return llm_model, "llm_model"

    generation_model = _normalize_model(tenant_config.get("generation_model"))
    if generation_model:
        log_key = (tenant_id, step_id or context)
        if log_key not in _logged_generation_fallback:
            _logged_generation_fallback.add(log_key)
            _logger.warning(
                "LLM model fallback to legacy generation_model. context=%s step=%s tenant=%s generation_model=%s",
                context,
                step_id,
                tenant_id,
                generation_model,
            )
        return generation_model, "generation_model"

    default_model = _normalize_model(getattr(settings, "default_llm_model", None))
    if default_model:
        return default_model, "settings_default"

    return None, "missing"
