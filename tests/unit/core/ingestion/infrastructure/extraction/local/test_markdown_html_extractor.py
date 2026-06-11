import pytest

from src.core.ingestion.infrastructure.extraction.local.markdown_html_extractor import (
    MarkdownHtmlExtractor,
    _clean_markdown,
    _scope_main_content,
)

try:
    import markitdown  # noqa: F401

    HAS_MARKITDOWN = True
except ImportError:
    HAS_MARKITDOWN = False


# Sphinx-like documentation page: site chrome around a main content area
# with heading hierarchy, a parameter table and prev/next footer links.
SPHINX_LIKE_PAGE = b"""
<html>
<head><title>backup set - Acme Mail Docs</title><style>.x{color:red}</style></head>
<body>
<nav class="navbar">Acme Mail Documentation <a href="/">Home</a></nav>
<div class="breadcrumbs"><a href="/cli">CLI</a> / backup set</div>
<div role="main">
  <div class="article-header-buttons"><a href="#">Repository</a> <a href="#">Open issue</a></div>
  <h1>backup set<a class="headerlink" href="#backup-set" title="Permalink">#</a></h1>
  <p>acme backup set enables the backup module for all accounts.</p>
  <h2>Parameter List<a class="headerlink" href="#params" title="Permalink">#</a></h2>
  <table>
    <tr><th>NAME</th><th>TYPE</th><th>DEFAULT</th></tr>
    <tr><td>accounts</td><td>Account Name[,..]</td><td>all</td></tr>
  </table>
  <div class="prev-next-area">
    <a href="prev.html">previous</a>
    <a href="next.html">next</a>
  </div>
</div>
<footer>By The Acme Team &copy; Copyright: ACME. Privacy &amp; Legal</footer>
</body>
</html>
"""


def test_scope_main_content_drops_chrome():
    scoped = _scope_main_content(SPHINX_LIKE_PAGE.decode())

    assert "backup set" in scoped
    assert "Parameter List" in scoped
    # chrome outside [role=main] is gone
    assert "navbar" not in scoped
    assert "breadcrumbs" not in scoped
    assert "Copyright" not in scoped
    # chrome inside [role=main] is gone
    assert "prev.html" not in scoped
    assert "headerlink" not in scoped


def test_clean_markdown_drops_noise_lines():
    dirty = (
        "# backup set\n\nReal content.\n\nprevious\n\nnext\n\n"
        "Repository\n\nOpen issue\n\n© Copyright: ACME.\n\nPrivacy & Legal\n\n"
        "By The Acme Team\n"
    )
    cleaned = _clean_markdown(dirty)

    assert "Real content." in cleaned
    for noise in ("previous", "next", "Repository", "©", "Privacy"):
        assert noise not in cleaned


@pytest.mark.asyncio
async def test_extract_produces_structured_markdown():
    if not HAS_MARKITDOWN:
        pytest.skip("markitdown not installed")

    extractor = MarkdownHtmlExtractor()
    assert extractor.name == "html_markdown"

    result = await extractor.extract(SPHINX_LIKE_PAGE, "text/html")

    assert result.extractor_used == "html_markdown"
    # heading hierarchy preserved as markdown headers
    assert "# backup set" in result.content
    assert "## Parameter List" in result.content
    # table preserved as pipe table, not flattened prose
    assert "| NAME | TYPE | DEFAULT |" in result.content
    assert "| accounts |" in result.content
    # permalink anchor artifact removed (no trailing "#" on the title text)
    assert "backup set#" not in result.content
    # chrome is gone
    for noise in ("previous", "next", "Repository", "Open issue", "Copyright"):
        assert noise not in result.content


@pytest.mark.asyncio
async def test_extract_falls_back_to_body_without_main_landmark():
    if not HAS_MARKITDOWN:
        pytest.skip("markitdown not installed")

    html = b"<html><body><h1>Title</h1><p>Plain page without landmarks.</p></body></html>"
    result = await MarkdownHtmlExtractor().extract(html, "text/html")

    assert "# Title" in result.content
    assert "Plain page without landmarks." in result.content


@pytest.mark.asyncio
async def test_details_summary_and_topic_aside_survive():
    if not HAS_MARKITDOWN:
        pytest.skip("markitdown not installed")

    html = b"""
    <html><body><div role="main">
      <h1>Monitoring</h1>
      <aside class="topic"><p>Component: MTA</p>
        <details><summary>SMTP</summary><p>Ports: 25, 465, 587</p></details>
        <details><summary>Milter</summary><p>Port: 7026</p></details>
      </aside>
      <aside class="bd-sidebar">sidebar chrome to drop</aside>
    </div></body></html>
    """
    result = await MarkdownHtmlExtractor().extract(html, "text/html")

    assert "Component: MTA" in result.content
    assert "SMTP" in result.content
    assert "25, 465, 587" in result.content
    assert "Port: 7026" in result.content
    assert "sidebar chrome" not in result.content
