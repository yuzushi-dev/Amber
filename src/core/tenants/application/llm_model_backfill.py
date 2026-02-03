from typing import Any


def _normalize_model(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def backfill_llm_model_config(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    llm_model = _normalize_model(config.get("llm_model"))
    generation_model = _normalize_model(config.get("generation_model"))

    updated_config = dict(config)
    changed = False

    if llm_model is None and generation_model is not None:
        updated_config["llm_model"] = generation_model
        llm_model = generation_model
        changed = True

    if generation_model is None and llm_model is not None:
        updated_config["generation_model"] = llm_model
        changed = True

    return updated_config, changed
