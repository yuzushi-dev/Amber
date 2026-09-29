"""Keep generated code only when it is present verbatim in supplied sources."""

import logging
import re
from collections.abc import Sequence

from src.core.generation.application.citations import protected_code_ranges

OMISSION_MARKER = "[Code omitted: no verbatim match in the supplied sources.]"
AMBIGUOUS_CODE_MARKER = (
    "[Code omitted: ambiguous code formatting. See original source excerpts.]"
)

logger = logging.getLogger(__name__)


def _source_match(fragment: str, source_excerpts: dict[int, str]) -> bool:
    return bool(fragment) and any(fragment in excerpt for excerpt in source_excerpts.values())


# Formatting-only differences between a generated literal and the stored source:
# Markdown punctuation escapes (``\*``), backslash-newline continuations, a leading
# ``user$`` shell prompt, and runs of horizontal whitespace inside a line
# (including NBSP and other Unicode spaces left by HTML sources).
# Leading indentation stays significant (YAML/Python).
_MARKDOWN_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_LINE_CONTINUATION = re.compile(r"\\[ \t]*(?:\r\n|\r|\n)[ \t]*")
_SHELL_PROMPT = re.compile(r"^[ \t]*\w*\$[ \t]+", re.MULTILINE)
_HORIZONTAL_SPACE = re.compile(r"[^\S\r\n]+")


def _canonical(text: str) -> str:
    text = _LINE_CONTINUATION.sub(" ", text)
    text = _MARKDOWN_ESCAPE.sub(r"\1", text)
    text = _SHELL_PROMPT.sub("", text)
    lines = []
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip(" \t"))
        lines.append(line[:indent] + _HORIZONTAL_SPACE.sub(" ", line[indent:]).rstrip())
    return "\n".join(lines).strip("\n")


def _canonical_match(fragment: str, canonical_excerpts: list[str]) -> bool:
    canonical = _canonical(fragment)
    return bool(canonical) and any(canonical in excerpt for excerpt in canonical_excerpts)


# Code that HTML-to-Markdown conversion squeezed into one table cell
# (``| ```  a &&  b ``` |``). Only these cells are compared with every
# whitespace run, newlines included, collapsed: elsewhere line structure stays
# significant.
_TABLE_CELL_CODE = re.compile(r"\|[ \t]*(`{3,})([^\r\n]+?)\1[ \t]*(?=\|)")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _table_cell_code(source_excerpts: dict[int, str]) -> list[str]:
    return [
        _flat(_canonical(match.group(2)))
        for excerpt in source_excerpts.values()
        for match in _TABLE_CELL_CODE.finditer(excerpt)
    ]


def _table_cell_match(body: str, table_cells: list[str]) -> bool:
    flat = _flat(_canonical(body))
    return bool(flat) and any(flat in cell for cell in table_cells)


# A JSON request body copied from a source example with its one sample number
# swapped for a placeholder (``{"value": VALUE}`` for ``{"value": 5368709120}``).
_JSON_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|<[^<>\s]+>|[A-Za-z_]\w*|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\S'
)
_JSON_NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"


def _json_placeholder_match(body: str, canonical_excerpts: list[str]) -> bool:
    body = body.strip()
    if not body.startswith(("{", "[")):
        return False
    tokens = _JSON_TOKEN.findall(body)
    slots = [
        index
        for index, token in enumerate(tokens)
        if (token[0] == "<" or token[0].isalpha() or token[0] == "_")
        and token not in ("true", "false", "null")
    ]
    # ponytail: exactly one unquoted placeholder, standing for a source number;
    # quoted or several placeholders stay omitted until a measured reject needs them.
    if len(slots) != 1:
        return False
    pattern = re.compile(
        r"\s*".join(
            _JSON_NUMBER if index == slots[0] else re.escape(token)
            for index, token in enumerate(tokens)
        )
    )
    return any(pattern.search(excerpt) for excerpt in canonical_excerpts)


_QUOTE_CLASS = "['\"`]"


def _quote_pattern(text: str) -> re.Pattern[str]:
    # Quotes are interchangeable and a backtick may follow any character: models
    # also drop the inner backticks of `` a == `TRUE` `` to fit one inline span.
    # ponytail: no leading "`?" (it would grab an enclosing fence's backtick), so a
    # literal that itself starts with a dropped backtick stays omitted.
    return re.compile(
        "".join((_QUOTE_CLASS if char in "'\"" else re.escape(char)) + "`?" for char in text)
    )


def _quote_repair(
    body: str, canonical_excerpts: list[str], table_cells: list[str]
) -> str | None:
    """Source text for a literal whose only change is its quote style.

    Markdown inline code cannot hold a single backtick, so models rewrite
    `` m(`a`) `` as ``m('a')`` or drop the backticks. When exactly one source
    literal matches with quotes/backticks interchangeable or backticks removed,
    that source text replaces the fragment.
    """
    canonical = _canonical(body)
    found = [m.group(0) for e in canonical_excerpts for m in _quote_pattern(canonical).finditer(e)]
    flat = _flat(canonical)
    found += [m.group(0) for cell in table_cells for m in _quote_pattern(flat).finditer(cell)]
    # The same literal found as prose and as a reflowed table cell is one match.
    return found[0] if len({_flat(text) for text in found}) == 1 else None


_FENCE_LINE = re.compile(r"( {0,3})(`{3,}|~{3,})([^\r\n]*)(\r\n|\r|\n)?")
_CITATIONS = re.compile(r"(?:\[\[Source: [\d, ]+\]\][ \t]*)+")


def _split_cited_fence_close(answer: str) -> str:
    """Move ``[[Source: n]]`` off a closing fence line onto its own line.

    CommonMark does not close a fence followed by text, so ``` [[Source: 3]]
    would leave the block open to the end of the answer and the whole tail
    would be checked (and omitted) as one code fragment.
    """
    out = []
    opener: str | None = None
    for line in answer.splitlines(keepends=True):
        match = _FENCE_LINE.fullmatch(line)
        if match and opener is None:
            opener = match.group(2)
        elif match and opener is not None and match.group(2)[0] == opener[0] and len(match.group(2)) >= len(opener):
            rest = match.group(3).strip()
            if not rest:
                opener = None
            elif _CITATIONS.fullmatch(rest):
                eol = match.group(4) or ""
                line = f"{match.group(1)}{match.group(2)}{eol or chr(10)}{rest}{eol}"
                opener = None
        out.append(line)
    return "".join(out)


def _code_markdown(fragment: str, text: str) -> str:
    """Wrap source text like the fragment it replaces, with a fence it cannot close."""
    run = max((len(m) for m in re.findall(r"`+", text)), default=0) + 1
    trailing = fragment[len(fragment.rstrip("\r\n")) :]
    opening = re.match(r" {0,3}(`{3,}|~{3,})([^\r\n]*)", fragment)
    if opening is None and "\n" not in text and "\r" not in text:
        fence = "`" * run
        return f"{fence} {text} {fence}{trailing}"
    fence = "`" * max(3, run)
    info = opening.group(2) if opening else ""
    return f"{fence}{info}\n{text}\n{fence}{trailing}"


def _query_echo(fragment: str, query: str) -> bool:
    """A one-line inline span echoing the user's own term, e.g. `Outl*` for "Outl"."""
    body = _inline_body(fragment)
    if body is None or "\n" in body or "\r" in body:
        return False
    term = body.strip("*\"' ")
    return bool(term) and term in query


def _ambiguous_inline_groups(
    answer: str,
    ranges: list[tuple[int, int]],
    source_excerpts: dict[int, str],
) -> list[tuple[int, int]]:
    """Reject line-local runs that Markdown splits around literal backticks."""
    canonical_excerpts = [_canonical(excerpt) for excerpt in source_excerpts.values()]
    inline_spans: list[tuple[int, int, int]] = []
    for start, end in ranges:
        fragment = answer[start:end]
        body = _inline_body(fragment)
        if (
            body is None
            or "\n" in fragment
            or "\r" in fragment
            or not fragment.startswith("`")
            or fragment.startswith("``")
        ):
            inline_spans.append((-1, -1, -1))
            continue
        line_start = max(answer.rfind("\n", 0, start), answer.rfind("\r", 0, start)) + 1
        inline_spans.append((start, end, line_start))

    groups: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(inline_spans):
        start, _, line_start = inline_spans[cursor]
        if start < 0:
            cursor += 1
            continue
        line_end = cursor + 1
        while line_end < len(inline_spans) and inline_spans[line_end][2] == line_start:
            line_end += 1

        # ponytail: bounded to one physical line; endpoint search is quadratic
        # in its inline-span count and should stay narrow until measured need.
        for group_start in range(cursor, line_end):
            found = False
            # two spans around one literal backtick run (`a`X`b`) are ambiguous too
            for group_end in range(line_end - 1, group_start, -1):
                raw_start = inline_spans[group_start][0]
                raw_end = inline_spans[group_end][1]
                if _source_match(answer[raw_start:raw_end], source_excerpts):
                    # Keep the pre-existing raw-verbatim match precedence.
                    cursor = group_end + 1
                    found = True
                    break
                body_start = inline_spans[group_start][0] + 1
                body_end = inline_spans[group_end][1] - 1
                candidate_body = answer[body_start:body_end]
                if "`" in candidate_body and (
                    _source_match(candidate_body, source_excerpts)
                    or _canonical_match(candidate_body, canonical_excerpts)
                ):
                    groups.append((raw_start, raw_end))
                    cursor = group_end + 1
                    found = True
                    break
            if found:
                break
        else:
            cursor = line_end

    return groups


def _inline_body(fragment: str) -> str | None:
    opener = re.match(r"^(`+)", fragment)
    if not opener:
        return None
    marker = opener.group(1)
    if len(marker) >= 3 and any(char in fragment for char in "\r\n"):
        return None
    ending = re.search(r"`+\Z", fragment)
    if (
        not ending
        or ending.group(0) != marker
        or len(fragment) <= 2 * len(marker)
    ):
        return None
    body = fragment[len(marker) : -len(marker)]
    exact_run = re.compile(r"(?<!`)`{" + str(len(marker)) + r"}(?!`)")
    if exact_run.search(body):
        # A matching delimiter before the range end can mean adjacent spans
        # were merged. Shorter or longer runs remain literal code content.
        return None
    return body


def _fenced_body(fragment: str) -> str | None:
    lines = fragment.splitlines(keepends=True)
    if len(lines) < 3:
        return None
    opening = re.fullmatch(r" {0,3}(`{3,}|~{3,})[^\r\n]*(?:\r\n|\r|\n)", lines[0])
    if not opening:
        return None
    marker = opening.group(1)
    closing = re.fullmatch(r" {0,3}(`{3,}|~{3,})[ \t]*(?:\r\n|\r|\n)?", lines[-1])
    if not closing or closing.group(1)[0] != marker[0] or len(closing.group(1)) < len(marker):
        return None

    body = "".join(lines[1:-1])
    # The line break immediately before the closing fence is structural. Keep
    # every earlier byte, including any intentional blank line in the source.
    if body.endswith("\r\n"):
        body = body[:-2]
    elif body.endswith(("\r", "\n")):
        body = body[:-1]
    early_close = re.compile(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*$")
    body_lines = body.splitlines()
    if any(early_close.fullmatch(line) for line in body_lines):
        return None
    return body


def _unwrapped_body(fragment: str) -> str | None:
    inline = _inline_body(fragment)
    if inline is not None:
        return inline
    return _fenced_body(fragment)


def _omission(fragment: str, marker: str = OMISSION_MARKER) -> str:
    # Trailing run of line breaks, kept verbatim (no regex: avoids ReDoS on long \r\n runs).
    return marker + fragment[len(fragment.rstrip("\r\n")):]


def _source_section(source_excerpts: dict[int, str]) -> str:
    entries = []
    for source_id, excerpt in source_excerpts.items():
        marker_length = max(3, max((len(m.group(0)) for m in re.finditer(r"`+", excerpt)), default=0) + 1)
        fence = "`" * marker_length
        body = excerpt
        separator = "" if body.endswith(("\r", "\n")) else "\n"
        entries.append(f"[[Source: {source_id}]]\n{fence}\n{body}{separator}{fence}")
    return "\n\nOriginal source excerpts\n\n" + "\n\n".join(entries)


def guard_literal_code(
    answer: str,
    source_excerpts: dict[int, str],
    query: str = "",
    history_answers: Sequence[str] = (),
) -> str:
    """Omit marked code ranges that cannot be matched verbatim to one source.

    A range that differs from one source literal only in quote style is replaced
    by that source text instead of being omitted.

    ``query`` is the user's question: an inline span that only echoes one of its
    terms is not a generated literal.

    ``history_answers`` are earlier assistant answers of the conversation; code
    repeated verbatim from them is accepted like source text (a follow-up often
    reuses commands whose source chunks the new retrieval did not return).
    ponytail: the history is client-supplied and not attributed to a model, so
    in mixed-model chats code from an unguarded answer is trusted too; upgrade
    path: server-side store of fragments that passed this guard, per conversation.
    """
    answer = _split_cited_fence_close(answer)
    ranges = protected_code_ranges(answer)
    if not ranges:
        return answer
    cited_sources = source_excerpts
    source_excerpts = {**source_excerpts}
    for index, text in enumerate(history_answers):
        if text:
            source_excerpts[-(index + 1)] = text

    ambiguous_groups = _ambiguous_inline_groups(answer, ranges, source_excerpts)
    checked_ranges = sorted(
        [
            (start, end)
            for start, end in ranges
            if not any(
                group_start <= start and end <= group_end
                for group_start, group_end in ambiguous_groups
            )
        ]
        + ambiguous_groups
    )
    replacements = []
    rejected = False
    canonical_excerpts = [_canonical(excerpt) for excerpt in source_excerpts.values()]
    table_cells = _table_cell_code(source_excerpts)
    for start, end in checked_ranges:
        fragment = answer[start:end]
        if (start, end) in ambiguous_groups:
            replacements.append(
                (start, end, _omission(fragment, AMBIGUOUS_CODE_MARKER))
            )
            rejected = True
            continue
        if _source_match(fragment, source_excerpts):
            continue
        body = _unwrapped_body(fragment)
        if body is not None and (
            _source_match(body, source_excerpts)
            or _canonical_match(body, canonical_excerpts)
            or _table_cell_match(body, table_cells)
            or _json_placeholder_match(body, canonical_excerpts)
        ):
            continue
        if _query_echo(fragment, query):
            continue
        repaired = (
            _quote_repair(body, canonical_excerpts, table_cells) if body is not None else None
        )
        if repaired is not None:
            replacements.append((start, end, _code_markdown(fragment, repaired)))
            continue
        logger.info("Literal code guard omitted fragment: %r", fragment[:160])
        replacements.append((start, end, _omission(fragment)))
        rejected = True

    for start, end, replacement in reversed(replacements):
        answer = answer[:start] + replacement + answer[end:]

    # ponytail: wrapper parsing deliberately rejects nested/ambiguous and HTML
    # code unless the full raw span matches; improve only from measured rejects.
    if rejected and cited_sources:
        answer += _source_section(cited_sources)
    return answer
