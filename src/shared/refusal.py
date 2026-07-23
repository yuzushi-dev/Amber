"""Shared refusal detection.

A "refusal" is a generated answer that says the knowledge base has no
information for the query. Two consumers must agree on what one looks like:

- the query routes, which must NOT persist a refusal as reusable conversation
  memory (it biases the retrieval-time rewriter into repeating the miss); and
- VerifiedQAService, which must NOT inject a refusal into future prompts as a
  positive few-shot example even if an admin accidentally "verified" it.

The dignified-refusal prompt makes a refusal look like a real answer (it appends
a "Closest documented topics:" section with cited sources), so a bare
substring check on the opening sentence is not enough: the model paraphrases
the pinned opener ("I don't have direct documentation on ...") and the answer
now carries sources. Detection therefore also matches an adverb-tolerant regex
and the section marker the refusal path emits.
"""

import re

REFUSAL_PHRASES: tuple[str, ...] = (
    "i don't have documentation",
    "i do not have documentation",
    "i don't have information",
    "i do not have information",
    "no documentation on",
    "couldn't find any relevant",
    "could not find any relevant",
    "i'm unable to find",
    "i am unable to find",
)

# Section title the dignified-refusal prompt appends — present only on refusals.
REFUSAL_MARKERS: tuple[str, ...] = ("closest documented topics",)

# Adverb-tolerant opener, e.g. "I don't have direct/specific/any documentation".
_REFUSAL_RE = re.compile(
    r"\bi\s+(?:don'?t|do not)\s+have\s+"
    r"(?:any\s+|direct\s+|specific\s+|relevant\s+|enough\s+|much\s+)*"
    r"(?:documentation|information|details|specifics|data)\b",
    re.IGNORECASE,
)


def text_looks_like_refusal(text: str | None) -> bool:
    """True if the answer text reads as a 'no information found' refusal."""
    if not text:
        return False
    lowered = text.lower()
    if any(p in lowered for p in REFUSAL_PHRASES):
        return True
    if any(m in lowered for m in REFUSAL_MARKERS):
        return True
    return _REFUSAL_RE.search(text) is not None
