"""
title: Amber (Knowledge Base)
author: Amber
version: 2.10.3
description: Query the Amber Enterprise Knowledge Base directly via @amber mention or by selecting the Amber model. Requires per-user API key via UserValves.
requirements: requests, pydantic, markdown-it-py==4.2.0
"""

import asyncio
import json
import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

import requests
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field

# Mirrored from src/core/generation/application/citations.py for standalone installation.

SUP_DIGITS = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
}


def to_unicode_sup(num: int) -> str:
    return "".join(SUP_DIGITS.get(d, d) for d in str(num))


def format_citations_to_unicode_sup(text: str) -> str:
    """
    Transforms citations like [[Source: 1]], [[Source: 2]] or [[Source: 1], [Source: 2]]
    into clean Unicode superscripts: [¹'²] or [¹] without any HTML tags.
    """
    pattern = re.compile(
        r"(\[\[?\s*Source:\s*\d+\s*\]\]?(?:\s*[,;]?\s*\[\[?\s*Source:\s*\d+\s*\]\]?)*)",
        re.IGNORECASE,
    )

    def replace_cluster(match: re.Match) -> str:
        cluster = match.group(0)
        nums = [int(n) for n in re.findall(r"Source:\s*(\d+)", cluster, re.IGNORECASE)]
        if not nums:
            return cluster
        seen = set()
        unique_nums = [n for n in nums if not (n in seen or seen.add(n))]
        sup_str = ",".join(to_unicode_sup(n) for n in unique_nums)
        return f"[{sup_str}]"

    return rewrite_unprotected(text, pattern, replace_cluster)


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

def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    return ""


def _clean_mention(text: str) -> str:
    text = re.sub(r"(?<!\w)@amber\b", "", text, flags=re.IGNORECASE)
    return text.strip()


def _history_from_messages(messages: list[dict], current_index: int) -> list[dict[str, str | None]]:
    """Return the two most recent user turns before the current user message."""
    turns = []
    for index, message in enumerate(messages[:current_index]):
        if message.get("role") != "user":
            continue
        query = _message_text(message.get("content"))
        if not query:
            continue
        answer = None
        for previous in messages[index + 1 : current_index]:
            if previous.get("role") == "user":
                break
            if previous.get("role") == "assistant":
                answer = _message_text(previous.get("content")) or None
                break
        query = _clean_mention(query)
        if not query:
            continue
        turns.append({"query": query[:10000], "answer": answer[:20000] if answer else None})
    return turns[-2:]


def _conversation_id(chat_id: str | None) -> str | None:
    return f"openwebui:{chat_id}" if chat_id and chat_id.strip() else None


class UserValves(BaseModel):
    amber_api_key: str = Field(
        default="",
        description="Your personal Amber API Key",
    )
    include_trace: bool = Field(
        default=False,
        description="Include retrieval trace in your personal responses for diagnostics",
    )


def format_source_entry(index: int, title_link: str, page_str: str, raw_text: str) -> str:
    """One numbered entry of the sources section.

    The snippet goes in a markdown blockquote without literal quotes: OpenWebUI's
    blockquote styling already adds typographic quotes, so wrapping it in "..."
    rendered as doubled quotes.
    """
    clean_snippet = " ".join(raw_text.split())
    if len(clean_snippet) > 200:
        clean_snippet = clean_snippet[:200] + "..."
    return f"{index}. 📄 {title_link}{page_str}\n   > {clean_snippet}"


class Pipe:
    class Valves(BaseModel):
        amber_api_url: str = Field(
            default="http://your-server.example.com",
            description="Base URL of the Amber API instance",
        )
        amber_api_key: str = Field(
            default="",
            description="Default system API Key (leave empty to require personal user API keys)",
        )
        search_mode: str = Field(
            default="basic",
            description="Search mode: 'basic', 'local', 'global', 'drift', 'structured'",
        )
        use_rewrite: bool = Field(
            default=True,
            description="Enable query rewriting in Amber for optimal retrieval accuracy",
        )
        max_chunks: int = Field(
            default=5,
            description="Initial retrieval chunk limit; sufficiency may expand context",
        )
        timeout_seconds: int = Field(
            default=120,
            description="Timeout in seconds for Amber response",
        )
        resolve_source_urls: bool = Field(
            default=True,
            description="Resolve and include clickable links to original document sources",
        )
        amber_model: str = Field(
            default="",
            description="Optional Amber LLM override (provider:model); empty uses Amber's configured model",
        )
        include_trace: bool = Field(
            default=False,
            description="Include Amber retrieval trace for diagnostics",
        )
        use_sufficiency_loop: bool = Field(
            default=True,
            description="Run one sufficiency retrieval round for better answers; may add latency and can be disabled",
        )

    class UserValves(BaseModel):
        amber_api_key: str = Field(
            default="",
            description="Your personal Amber API Key",
        )

        include_trace: bool = Field(
            default=False,
            description="Include retrieval trace in your personal responses for diagnostics",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.user_valves = self.UserValves()
        self._url_cache = {}

    def _get_api_key(self, __user__: dict | None = None) -> str:
        if __user__ and "valves" in __user__ and __user__["valves"]:
            raw_v = __user__["valves"]
            if hasattr(raw_v, "amber_api_key") and raw_v.amber_api_key:
                return str(raw_v.amber_api_key).strip()
            if isinstance(raw_v, dict) and raw_v.get("amber_api_key"):
                return str(raw_v["amber_api_key"]).strip()
        return self.valves.amber_api_key.strip() if self.valves.amber_api_key else ""

    def _get_document_url(self, doc_id: str, api_key: str) -> str | None:
        if not doc_id or doc_id.startswith("rule_doc"):
            return None
        if doc_id in self._url_cache:
            return self._url_cache[doc_id]
        try:
            base = self.valves.amber_api_url.rstrip("/")
            url = f"{base}/v1/documents/{doc_id}"
            headers = {"X-API-Key": api_key}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                meta = data.get("metadata") or {}
                source_url = meta.get("source_url") or data.get("source_url")
                self._url_cache[doc_id] = source_url
                return source_url
        except Exception:
            pass
        return None

    async def pipe(
        self,
        body: dict,
        __user__: dict = None,
        __event_emitter__: Callable[[dict[str, Any]], Any] | None = None,
        __task__: str = None,
        __chat_id__: str | None = None,
    ) -> str:
        # Handle background title/tag generation tasks quickly
        if __task__:
            return "Amber Knowledge Query"

        api_key = self._get_api_key(__user__)
        if not api_key:
            return (
                "⚠️ No Amber API Key configured for your account.\n\n"
                "To use `@amber` or the Amber model, please configure your personal **Amber API Key** in your settings:\n"
                "1. Go to **Workspace** > **Functions** > click the ⚙️ **Valves** icon next to *Amber* (or in your user profile **Settings** > **Valves**).\n"
                "2. Enter your key in the `amber_api_key` field and click Save."
            )

        user_valves = (__user__ or {}).get("valves")
        if isinstance(user_valves, dict):
            user_include_trace = user_valves.get("include_trace") is True
        else:
            user_include_trace = getattr(user_valves, "include_trace", False) is True
        include_trace = self.valves.include_trace is True or user_include_trace

        # Extract last user message
        messages = body.get("messages")
        messages_available = isinstance(messages, list)
        if not messages_available:
            messages = []
        raw_msg = ""
        current_index = None
        for index in range(len(messages) - 1, -1, -1):
            m = messages[index]
            if m.get("role") == "user":
                current_index = index
                raw_msg = _message_text(m.get("content"))
                break

        # Clean @amber mention from query
        query = _clean_mention(raw_msg)

        if not query:
            return "How can I help you? Ask any question about the product documentation (e.g. `@amber How do I configure 2FA?`)."

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": "🔍 Querying Amber Knowledge Base...",
                        "done": False,
                    },
                }
            )

        base = self.valves.amber_api_url.rstrip("/")
        url = f"{base}/v1/query"
        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "options": {
                "search_mode": self.valves.search_mode,
                "use_rewrite": self.valves.use_rewrite,
                "max_chunks": self.valves.max_chunks,
                "include_sources": True,
                "stream": False,
                "include_trace": include_trace,
                "use_sufficiency_loop": self.valves.use_sufficiency_loop,
                "max_sufficiency_rounds": 1,
            },
        }
        if self.valves.amber_model.strip():
            payload["options"]["model"] = self.valves.amber_model.strip()
        if messages_available:
            payload["history"] = (
                _history_from_messages(messages, current_index) if current_index is not None else []
            )
        conversation_id = _conversation_id(__chat_id__)
        if conversation_id:
            payload["conversation_id"] = conversation_id

        try:
            # Requests keeps its own timeout; cancelling this await cannot stop its worker thread.
            resp = await asyncio.to_thread(
                requests.post,
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.timeout_seconds,
            )

            if resp.status_code != 200:
                err_msg = f"Error from Amber ({resp.status_code}): {resp.text}"
                if __event_emitter__:
                    await __event_emitter__(
                        {"type": "status", "data": {"description": "Amber Error", "done": True}}
                    )
                return err_msg

            data = resp.json()
            raw_answer = data.get("answer", "No answer generated by Amber.")
            if data.get("model"):
                raw_answer += f"\n\n*Amber model: {data['model']}*"
            sources = data.get("sources", [])

            out = [format_citations_to_unicode_sup(raw_answer)]
            if include_trace and data.get("trace"):
                trace_json = json.dumps(data["trace"], ensure_ascii=False, indent=2)
                out.append(
                    f"\n\n<details><summary>Retrieval trace</summary>\n\n"
                    f"```json\n{trace_json}\n```\n</details>"
                )

            # Format in-text citations into clean Unicode superscripts (e.g. [¹'²] or [¹])
            # Append formatted sources
            if sources:
                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "status",
                            "data": {
                                "description": f"📚 Fetching source references ({len(sources)} sources)...",
                                "done": False,
                            },
                        }
                    )

                sources_section = ["### Sources & Original References:"]
                valid_count = 0
                for s in sources:
                    doc_id = s.get("document_id") or ""
                    if doc_id.startswith("rule_doc"):
                        continue
                    valid_count += 1
                    doc_name = s.get("document_name") or s.get("title") or doc_id or "Document"
                    page = s.get("page")
                    page_str = f" (Page {page})" if page is not None else ""

                    source_url = (
                        await asyncio.to_thread(self._get_document_url, doc_id, api_key)
                        if self.valves.resolve_source_urls
                        else None
                    )
                    if source_url:
                        title_link = f"[{doc_name}]({source_url})"
                    else:
                        title_link = f"**{doc_name}**"

                    raw_text = s.get("text") or s.get("content_preview") or ""
                    sources_section.append(
                        format_source_entry(valid_count, title_link, page_str, raw_text)
                    )

                if valid_count > 0:
                    out.append("\n\n" + "\n\n".join(sources_section))

            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": "Completed",
                            "done": True,
                        },
                    }
                )

            return "\n\n".join(out)

        except requests.exceptions.Timeout:
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "Timeout", "done": True}}
                )
            return "Timeout: the request to Amber exceeded the time limit."
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "Error", "done": True}}
                )
            return f"Error while querying Amber: {e}"

