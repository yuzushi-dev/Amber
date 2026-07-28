"""Shared refusal detection.

A "refusal" is a generated answer that says the knowledge base has no
information for the query. Two consumers must agree on what one looks like:

- the query routes, which must NOT persist a refusal as reusable conversation
  memory (it biases the retrieval-time rewriter into repeating the miss); and
- VerifiedQAService, which must NOT inject a refusal into future prompts as a
  positive few-shot example even if an admin accidentally "verified" it.

The dignified-refusal prompt makes a refusal look like a real answer: it
appends a "Closest documented topics:" section with cited sources, so a
no-sources check alone is no longer a sufficient defense on its own — a
refusal can carry sources now. `text_looks_like_refusal` is the text-based
backstop for that case; `if not sources` in the caller remains the first line
of defense for the (still common) case of a refusal with none.

Anchoring REFUSAL_PHRASES / _REFUSAL_RE
----------------------------------------
Phrase and regex matching only look at the text that precedes the FIRST
"[[Source:" citation (or the whole text, if there is no citation at all).
This isn't a fixed-size window: it follows the actual shape a refusal vs. a
real cited answer produces —

- A real, well-sourced answer can legitimately contain a hedge sentence
  ("I do not have details on the exact timeout value") *after* it has
  already cited a source for the substantive part of the answer. Once a
  citation has appeared, further "I don't have..." language downstream is
  not a sign the whole answer is a refusal.
- A refusal, dignified or not, never has a real citation before its opening
  ("I don't have documentation on that topic", possibly after a short
  preamble): any citations it carries are pinned to the appended "Closest
  documented topics" section, which always comes after the refusal opener.

So scanning "everything before the first citation" catches short preambles
("Thanks for asking, I don't have documentation...") and rejects a hedge that
trails real, already-cited content, without a magic character count.

REFUSAL_MARKERS ("closest documented topics" / its Italian forms) is checked
against the *whole* text regardless of citations: that section is only ever
appended by the refusal path, so a full-text check is safe and needed (there
is no "before the opener" region to anchor a trailing marker to).

Known limitation (not fixed here — no cheap text heuristic solves it): a
valid answer that opens with a hedge AND its substantive, cited content in
the very same sentence, before any "[[Source:" appears, still reads as a
refusal. E.g. "I don't have specific details on the exact configuration, but
the default timeout is 60 seconds, set it in mail.cf [[Source: 4]]." is a
real, useful answer but is flagged True. See
test_hedge_before_citation_in_same_sentence_is_a_known_false_positive in
tests/unit/test_refusal_prompt.py, which pins this on purpose.

Language coverage
------------------
Phrase/marker lists cover English and Italian (the `default` tenant's
rag_system_prompt override tells the model to answer in the user's language,
so refusals show up in Italian in production). This is a best-effort,
pattern-based detector, not an exhaustive one — it will miss refusals phrased
in any other language, or in EN/IT wording not covered by the lists below.
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
    "non ho documentazione",
    "non ho informazioni",
    "non ho trovato",
    "non sono in grado di trovare",
    "non ci sono documenti",
)

# Section title the dignified-refusal prompt appends — present only on
# refusals. Checked against the whole text (see module docstring): it's a
# trailing marker, not an opener, so there's no "before the first citation"
# region to anchor it to.
REFUSAL_MARKERS: tuple[str, ...] = (
    "closest documented topics",
    "argomenti documentati più vicini",
    "argomenti correlati documentati",
)

# Adverb-tolerant opener, e.g. "I don't have direct/specific/any documentation".
_REFUSAL_RE = re.compile(
    r"\bi\s+(?:don'?t|do not)\s+have\s+"
    r"(?:any\s+|direct\s+|specific\s+|relevant\s+|enough\s+|much\s+)*"
    r"(?:documentation|information|details|specifics|data)\b",
    re.IGNORECASE,
)

# Citations are only ever attached to real, provided sources; a refusal's own
# citations (if any) live in the appended "Closest documented topics"
# section, never before its opening. See module docstring.
_CITATION_MARKER = "[[Source:"


def text_looks_like_refusal(text: str | None) -> bool:
    """True if the answer text reads as a 'no information found' refusal."""
    if not text:
        return False
    citation_idx = text.find(_CITATION_MARKER)
    region = text if citation_idx == -1 else text[:citation_idx]
    opening = region.lower()
    if any(p in opening for p in REFUSAL_PHRASES):
        return True
    if _REFUSAL_RE.search(region) is not None:
        return True
    lowered = text.lower()
    return any(m in lowered for m in REFUSAL_MARKERS)
