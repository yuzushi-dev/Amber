"""Source-preserving Markdown code ranges for citation rewrites."""

import re
from collections.abc import Callable
from html.parser import HTMLParser

from markdown_it import MarkdownIt


def _line_offsets(text: str) -> tuple[list[int], list[int]]:
    starts = [0]
    ends = []
    for match in re.finditer(r"\r\n|\r|\n", text):
        ends.append(match.start())
        starts.append(match.end())
    ends.append(len(text))
    return starts, ends


def _html_code_ranges(text: str, ignored: list[tuple[int, int]]) -> list[tuple[int, int]]:
    line_starts = [0] + [match.end() for match in re.finditer(r"\n", text)]
    ranges = []
    stack: list[tuple[str, int]] = []

    class CodeTagParser(HTMLParser):
        def _offset(self) -> int:
            line, column = self.getpos()
            return line_starts[line - 1] + column

        def _inside_markdown_code(self, offset: int) -> bool:
            return any(start <= offset < end for start, end in ignored)

        def handle_starttag(self, tag, attrs):
            if tag in {"code", "pre"}:
                start = self._offset()
                if not self._inside_markdown_code(start) and not is_escaped(text, start):
                    stack.append((tag, start))

        def handle_startendtag(self, tag, attrs):
            return

        def handle_endtag(self, tag):
            if tag not in {"code", "pre"}:
                return
            end_start = self._offset()
            if self._inside_markdown_code(end_start) or is_escaped(text, end_start):
                return
            close = text.find(">", end_start)
            end = close + 1 if close >= 0 else len(text)
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == tag:
                    ranges.extend((start, end) for _, start in stack[index:])
                    del stack[index:]
                    break

    parser = CodeTagParser(convert_charrefs=False)
    parser.feed(text)
    ranges.extend((start, len(text)) for _, start in stack)
    return ranges


def _block_range(
    line_map: list[int] | tuple[int, int] | None, starts: list[int], text_len: int
) -> tuple[int, int] | None:
    if not line_map or line_map[0] < 0 or line_map[1] > len(starts):
        return None
    end = starts[line_map[1]] if line_map[1] < len(starts) else text_len
    return starts[line_map[0]], end


def _inline_offset(
    src: str,
    pos: int,
    line_map: list[int] | tuple[int, int] | None,
    lines: list[str],
    starts: list[int],
) -> int | None:
    if not line_map or pos < 0 or pos > len(src):
        return None
    before = src[:pos]
    row = before.count("\n")
    source_row = line_map[0] + row
    if source_row >= len(lines) or source_row >= line_map[1]:
        return None
    inline_line = src.split("\n")[row]
    original_line = lines[source_row]
    matches = [
        index
        for index in range(len(original_line) + 1)
        if original_line.startswith(inline_line, index)
    ]
    if len(matches) != 1:
        return None
    column = len(before.rsplit("\n", 1)[-1])
    if column > len(inline_line):
        return None
    return starts[source_row] + matches[0] + column


def protected_code_ranges(text: str) -> list[tuple[int, int]]:
    """Return original source offsets for code blocks and inline code spans."""
    lines_start, lines_end = _line_offsets(text)
    lines = [text[start:end] for start, end in zip(lines_start, lines_end, strict=True)]
    parser = MarkdownIt("commonmark")
    spans: list[tuple[str, int, int, list[int] | tuple[int, int] | None]] = []
    original_backticks = next(
        rule.fn
        for rule in parser.inline.ruler.__rules__
        if rule.name == "backticks"
    )

    def capture_backticks(state, silent):
        start = state.pos
        matched = original_backticks(state, silent)
        if matched and not silent and state.tokens and state.tokens[-1].type == "code_inline":
            spans.append((state.src, start, state.pos, state.env.get("_amber_source_map")))
        return matched

    def parse_inline_with_map(state):
        for token in state.tokens:
            if token.type == "inline":
                state.env["_amber_source_map"] = token.map
                token.children = []
                state.md.inline.parse(token.content, state.md, state.env, token.children)

    parser.inline.ruler.at("backticks", capture_backticks)
    parser.core.ruler.at("inline", parse_inline_with_map)
    tokens = parser.parse(text)

    ranges = []
    for token in tokens:
        if token.type in ("fence", "code_block"):
            block = _block_range(token.map, lines_start, len(text))
            if block:
                ranges.append(block)

    failed_blocks = set()
    mapped_spans = []
    for src, start, end, line_map in spans:
        raw_start = _inline_offset(src, start, line_map, lines, lines_start)
        raw_end = _inline_offset(src, end, line_map, lines, lines_start)
        block = tuple(line_map) if line_map else None
        if raw_start is None or raw_end is None or raw_end < raw_start:
            failed_blocks.add(block)
        else:
            mapped_spans.append((block, raw_start, raw_end))

    for line_map in failed_blocks:
        block = _block_range(line_map, lines_start, len(text))
        ranges.append(block or (0, len(text)))
    ranges.extend((start, end) for block, start, end in mapped_spans if block not in failed_blocks)
    ranges.extend(_html_code_ranges(text, ranges))
    return _merge_ranges(ranges)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def is_protected(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < right and end > left for left, right in ranges)


def is_escaped(text: str, start: int) -> bool:
    count = 0
    start -= 1
    while start >= 0 and text[start] == "\\":
        count += 1
        start -= 1
    return count % 2 == 1


def rewrite_unprotected(text: str, pattern: re.Pattern, replacement: Callable) -> str:
    ranges = protected_code_ranges(text)
    changes = [
        (match.start(), match.end(), replacement(match))
        for match in pattern.finditer(text)
        if not is_protected(match.start(), match.end(), ranges)
        and not is_escaped(text, match.start())
    ]
    for start, end, value in reversed(changes):
        text = text[:start] + value + text[end:]
    return text
