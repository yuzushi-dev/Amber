"""
Effective Tenant Config Helpers
===============================

Helpers for resolving inherited tenant configuration from the default tenant.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_TENANT_ID = "default"
NON_INHERITABLE_TOP_LEVEL_KEYS = {"active_vector_collection"}


def merge_tenant_config(
    default_config: dict[str, Any] | None,
    tenant_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge default tenant config with tenant overrides without mutating inputs."""
    return _merge_dicts(default_config or {}, tenant_config or {}, top_level=True)


def merge_rule_lists(
    default_rules: list[str] | None,
    tenant_rules: list[str] | None,
) -> list[str]:
    """Return effective rules with default rules first."""
    return list(default_rules or []) + list(tenant_rules or [])


def resolve_rag_prompts(
    base_system_prompt: str,
    base_user_prompt: str,
    tenant_config: dict[str, Any] | None,
    rules_addendum: str = "",
) -> tuple[str, str]:
    """Resolve effective RAG prompts, preserving domain rules after tenant overrides."""
    config = tenant_config or {}
    system_prompt = config.get("rag_system_prompt") or base_system_prompt
    user_prompt = config.get("rag_user_prompt") or base_user_prompt

    if rules_addendum and rules_addendum not in system_prompt:
        system_prompt = f"{system_prompt}{rules_addendum}"

    return system_prompt, user_prompt


def _merge_dicts(
    defaults: dict[str, Any],
    overrides: dict[str, Any],
    *,
    top_level: bool,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    for key in set(defaults) | set(overrides):
        if top_level and key in NON_INHERITABLE_TOP_LEVEL_KEYS:
            override_value = overrides.get(key)
            if override_value is not None:
                merged[key] = deepcopy(override_value)
            continue

        has_override = key in overrides
        override_value = overrides.get(key)
        default_value = defaults.get(key)

        if has_override:
            if override_value is None:
                if key in defaults:
                    merged[key] = deepcopy(default_value)
                continue

            if isinstance(default_value, dict) and isinstance(override_value, dict):
                merged[key] = _merge_dicts(default_value, override_value, top_level=False)
            else:
                merged[key] = deepcopy(override_value)
            continue

        merged[key] = deepcopy(default_value)

    return merged
