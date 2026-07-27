"""Guard the "dignified refusal" prompt contract.

The default RAG system prompt must (a) keep the exact refusal phrase — log
triage and downstream detection key off it — and (b) instruct the model to
list closest documented topics from the already-provided sources, cited.
Prompt-only change: these tests pin the template contract, not LLM behavior.
"""

from src.core.generation.application.prompts.templates import PROMPTS, SYSTEM_PROMPT_v1
from src.core.tenants.application.effective_config import resolve_rag_prompts
from src.shared.refusal import text_looks_like_refusal

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


# --- Behavioural refusal-detection tests (shared detector) --------------------


def test_paraphrased_refusal_opener_detected():
    # Model deviates from the pinned opener with an adverb — must still count.
    assert text_looks_like_refusal(
        "I don't have direct documentation on that topic, but here are some pointers."
    )
    assert text_looks_like_refusal("I do not have specific information about that.")


def test_dignified_refusal_with_sources_detected():
    # New prompt shape: refusal opener + cited "Closest documented topics" section.
    ans = (
        "I don't have documentation on how to integrate X.\n\n"
        "Closest documented topics:\n- Foo [[Source: 1]]\n- Bar [[Source: 2]]"
    )
    assert text_looks_like_refusal(ans)
    # The section marker alone is enough even if the opener is reworded.
    assert text_looks_like_refusal("No direct match. Closest documented topics: ...")


def test_real_answer_not_flagged_as_refusal():
    assert not text_looks_like_refusal(
        "To create a distribution list, open the Admin Panel and select Domains [[Source: 1]]."
    )
    assert not text_looks_like_refusal("")


def test_valid_answer_with_mid_text_hedge_is_not_refusal():
    # Regression test: a real, sourced answer that happens to contain a hedge
    # sentence AFTER its first citation must not be classified as a refusal.
    # Fails if detection goes back to scanning the whole text unanchored.
    assert not text_looks_like_refusal(
        "Configure the MTA as described [[Source: 2]]. I do not have details "
        "on the exact timeout value, but the default is 60s [[Source: 3]]."
    )


def test_refusal_at_opening_is_detected():
    assert text_looks_like_refusal("I don't have documentation on that topic.")
    # Adverb-tolerant opener, still no citation before it.
    assert text_looks_like_refusal(
        "I don't have direct documentation on the exact configuration syntax."
    )


def test_italian_refusal_is_detected():
    assert text_looks_like_refusal("Non ho documentazione su questo argomento.")


def test_marker_anywhere_is_detected():
    # Opening carries no refusal pattern; the trailing marker alone is enough.
    assert text_looks_like_refusal(
        "Here is what's related to your query.\n\n"
        "Closest documented topics:\n- Foo [[Source: 1]]"
    )


def test_short_preamble_before_refusal_is_detected():
    assert text_looks_like_refusal(
        "Thanks for asking. I don't have documentation on that topic."
    )


def test_hedge_before_citation_in_same_sentence_is_a_known_false_positive():
    # Known limitation, pinned on purpose (see src/shared/refusal.py
    # docstring): a valid answer whose opening sentence mixes a hedge with
    # its own substantive, cited content — before any citation appears — is
    # indistinguishable from a real refusal opener with cheap text matching.
    # This is a real, useful answer, but it IS flagged as a refusal today.
    assert text_looks_like_refusal(
        "I don't have specific details on the exact configuration, but the "
        "default timeout is 60 seconds, set it in mail.cf [[Source: 4]]."
    )
