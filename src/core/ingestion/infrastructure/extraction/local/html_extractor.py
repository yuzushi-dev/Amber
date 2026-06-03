"""
HTML Extractor
==============

BeautifulSoup-based extractor for HTML files.
Handles elements that unstructured skips, including <details>/<summary>.
"""

import logging
import time

from src.core.ingestion.infrastructure.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)

_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "iframe"}

# Block-level tags that produce independent text segments
_BLOCK_TAGS = {
    "p", "div", "section", "article", "aside", "main",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "dt", "dd",
    "blockquote", "pre",
    "details", "summary",
    "tr", "td", "th",
}


def _collect_leaf_blocks(root) -> list[str]:
    """
    Walk the DOM tree and emit text only from innermost block elements,
    preventing ancestor blocks from double-counting their descendants.
    """
    from bs4 import Tag

    results: list[str] = []

    def _has_block_child(node: Tag) -> bool:
        for child in node.children:
            if isinstance(child, Tag) and child.name and child.name.lower() in _BLOCK_TAGS:
                return True
        return False

    def walk(node: Tag) -> None:
        if not isinstance(node, Tag):
            return
        tag_name = node.name.lower() if node.name else ""
        if tag_name in _SKIP_TAGS:
            return

        is_block = tag_name in _BLOCK_TAGS

        if is_block:
            if not _has_block_child(node):
                # Leaf block — emit full text
                text = node.get_text(separator=" ", strip=True)
                if text:
                    results.append(text)
            else:
                # Container block — recurse into children individually
                for child in node.children:
                    walk(child)
        else:
            for child in node.children:
                walk(child)

    walk(root)
    return results


class HtmlExtractor(BaseExtractor):
    """
    HTML extractor using BeautifulSoup.
    Correctly handles <details>/<summary> and other HTML5 disclosure elements.
    """

    @property
    def name(self) -> str:
        return "html_bs4"

    async def extract(self, file_content: bytes, mime_type: str, **kwargs) -> ExtractionResult:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise ImportError("beautifulsoup4 is not installed.") from exc

        start = time.time()

        try:
            html = file_content.decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")

            for tag in soup.find_all(list(_SKIP_TAGS)):
                tag.decompose()

            body = soup.find("body") or soup
            lines = _collect_leaf_blocks(body)
            content = "\n\n".join(lines)

            elapsed = (time.time() - start) * 1000
            return ExtractionResult(
                content=content,
                tables=[],
                metadata={},
                extractor_used=self.name,
                confidence=0.85,
                extraction_time_ms=elapsed,
            )

        except Exception as exc:
            logger.error(f"HTML extraction failed: {exc}")
            raise RuntimeError(f"HTML extraction failed: {exc}") from exc
