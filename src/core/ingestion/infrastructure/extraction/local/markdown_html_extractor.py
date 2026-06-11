"""
Markdown HTML Extractor
=======================

Pre-ingestion normalizer for HTML documents: scopes the page to its main
content (dropping site chrome such as navigation, prev/next links and
footers), then converts it to structured Markdown via MarkItDown so that
heading hierarchy and tables survive extraction. The header-aware chunker
can then split by section instead of falling back to paragraph splitting.

Falls back to the flat-text HtmlExtractor when MarkItDown is unavailable.
"""

import io
import logging
import re
import time

from src.core.ingestion.infrastructure.extraction.base import BaseExtractor, ExtractionResult
from src.core.ingestion.infrastructure.extraction.local.html_extractor import HtmlExtractor

logger = logging.getLogger(__name__)

# First match wins. Ordered most-specific → most-generic so themed doc sites
# (Sphinx, help centers) scope tighter than a bare <main>.
_CONTENT_SELECTORS = (
    "div.article-body",  # Zendesk help center article
    "[role=main]",  # Sphinx themes (pydata, book, RTD)
    "div.document",  # classic Sphinx
    "main",
    "article",
)

# Scoping must retain at least this share of the page text (after chrome
# removal), otherwise the selector grabbed a fragment and we keep the body.
_MIN_SCOPE_TEXT_RATIO = 0.5

# Removed wherever they appear inside the scoped content.
_CHROME_SELECTORS = (
    "nav",
    "header",
    "footer",
    "aside",
    "a.headerlink",  # Sphinx ¶/# permalink anchors that leak into text
    ".article-header-buttons",  # Sphinx pydata-theme "Repository / Open issue" buttons
    ".prev-next-area",
    ".prev-next-footer",
    "[class*=breadcrumb]",
    ".edit-this-page",
    ".sourcelink",
    ".article-votes",  # Zendesk "Was this article helpful?"
    ".article-relatives",  # Zendesk related articles block
)

# Safety net on the converted Markdown: standalone chrome lines that survive
# scoping on themes that render buttons inside the main container.
_NOISE_LINE_PATTERNS = (
    re.compile(r"^\s*(previous|next)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[?\s*(previous|next)\b[^|]*\]\(.*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*©.*$"),
    re.compile(r"^\s*copyright\b.*$", re.IGNORECASE),
    re.compile(r"^\s*privacy\s*&\s*legal\s*$", re.IGNORECASE),
    re.compile(
        r"^\s*((repository|open issue|edit on github|skip to (main )?content)\s*)+$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*was this article helpful\??\s*$", re.IGNORECASE),
    re.compile(r"^\s*by the .{0,40} team\s*$", re.IGNORECASE),
)


def _scope_main_content(html: str) -> str:
    """Return the HTML of the main content area, stripped of chrome elements."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body") or soup

    # Strip chrome at page level first, so the body fallback is already clean.
    for selector in _CHROME_SELECTORS:
        for tag in body.select(selector):
            tag.decompose()
    for tag in body.find_all(("script", "style", "noscript", "iframe")):
        tag.decompose()

    body_text_len = len(body.get_text(strip=True)) or 1
    for selector in _CONTENT_SELECTORS:
        scope = body.select_one(selector)
        if scope is None:
            continue
        # Guard: a landmark that holds a small fraction of the page text is a
        # mismatch (e.g. an unrelated #content fragment) — keep the body.
        if len(scope.get_text(strip=True)) / body_text_len >= _MIN_SCOPE_TEXT_RATIO:
            return str(scope)
        break

    return str(body)


def _clean_markdown(markdown: str) -> str:
    """Drop residual chrome lines and collapse excess blank lines."""
    lines = []
    last_heading = None
    for line in markdown.splitlines():
        if any(p.match(line) for p in _NOISE_LINE_PATTERNS):
            continue
        if line.startswith("#"):
            # Sphinx CLI pages repeat the page title as first section heading
            if last_heading and line.lstrip("# ").strip() == last_heading:
                continue
            last_heading = line.lstrip("# ").strip()
        elif line.strip():
            last_heading = None
        lines.append(line.rstrip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class MarkdownHtmlExtractor(BaseExtractor):
    """
    HTML extractor producing clean structured Markdown.

    Scope → strip chrome → MarkItDown → line-level noise filter.
    """

    @property
    def name(self) -> str:
        return "html_markdown"

    async def extract(self, file_content: bytes, mime_type: str, **kwargs) -> ExtractionResult:
        start = time.time()

        try:
            from markitdown import MarkItDown, StreamInfo
        except ImportError:
            logger.warning("markitdown not installed — falling back to flat HtmlExtractor")
            return await HtmlExtractor().extract(file_content, mime_type, **kwargs)

        try:
            html = file_content.decode("utf-8", errors="replace")
            scoped = _scope_main_content(html)

            converter = MarkItDown(enable_plugins=False)
            result = converter.convert(
                io.BytesIO(scoped.encode("utf-8")),
                stream_info=StreamInfo(extension=".html", mimetype="text/html"),
            )
            content = _clean_markdown(result.markdown or "")

            if not content:
                raise ValueError("empty markdown after normalization")

            elapsed = (time.time() - start) * 1000
            return ExtractionResult(
                content=content,
                tables=[],
                metadata={"normalizer": "markitdown"},
                extractor_used=self.name,
                confidence=0.9,
                extraction_time_ms=elapsed,
            )
        except Exception as exc:
            logger.warning(f"Markdown normalization failed ({exc}) — falling back to HtmlExtractor")
            return await HtmlExtractor().extract(file_content, mime_type, **kwargs)
