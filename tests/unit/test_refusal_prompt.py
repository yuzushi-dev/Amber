"""Guard the "dignified refusal" prompt contract.

The default RAG system prompt must (a) keep the exact refusal phrase — log
triage and downstream detection key off it — and (b) instruct the model to
list closest documented topics from the already-provided sources, cited.
Prompt-only change: these tests pin the template contract, not LLM behavior.
"""

from src.core.generation.application.prompts.templates import PROMPTS, SYSTEM_PROMPT_v1
from src.core.tenants.application.effective_config import resolve_rag_prompts

REFUSAL = "I don't have documentation on that topic."
POINTER_MARKER = "Closest documented topics:"


def test_refusal_phrase_kept_verbatim():
    assert REFUSAL in SYSTEM_PROMPT_v1


def test_closest_topics_instruction_present_and_cited():
    assert POINTER_MARKER in SYSTEM_PROMPT_v1
    tail = SYSTEM_PROMPT_v1[SYSTEM_PROMPT_v1.find(POINTER_MARKER):][:400]
    assert "[[Source: X]]" in tail  # pointers must be bound to real cited sources


def test_registry_serves_updated_prompt():
    assert POINTER_MARKER in PROMPTS["rag_system"]["latest"]


def test_default_resolution_path_carries_instruction():
    system, _ = resolve_rag_prompts(
        base_system_prompt=PROMPTS["rag_system"]["latest"],
        base_user_prompt=PROMPTS["rag_user"]["latest"],
        tenant_config={},
    )
    assert REFUSAL in system and POINTER_MARKER in system


def test_tenant_override_bypasses_default():
    # Known limitation, pinned on purpose: a tenant-level rag_system_prompt
    # override replaces the default template and will NOT get the pointers.
    system, _ = resolve_rag_prompts(
        base_system_prompt=PROMPTS["rag_system"]["latest"],
        base_user_prompt=PROMPTS["rag_user"]["latest"],
        tenant_config={"rag_system_prompt": "CUSTOM"},
    )
    assert system == "CUSTOM"
