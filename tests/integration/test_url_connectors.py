"""
URL Fetcher and Connector Integration Tests
============================================

Tests for URL ingestion and connector framework.
"""

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.connectors.base import ConnectorItem
from src.core.connectors.zendesk import ZendeskConnector
from src.core.ingestion.url_fetcher import URLFetcher


@pytest.mark.asyncio
async def test_url_fetcher_basic():
    """Test URL fetcher with mocked response."""
    fetcher = URLFetcher()

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.content = b"Hello, World!"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.url = "https://example.com"
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_cm

        result = await fetcher.fetch("https://example.com")

        assert result.content == b"Hello, World!"
        assert result.content_type == "text/html"


def test_url_fetcher_invalid_url():
    """Test URL validation."""
    fetcher = URLFetcher()

    import pytest
    with pytest.raises(ValueError, match="Invalid URL"):
        import asyncio
        asyncio.run(fetcher.fetch("not-a-url"))


def test_url_fetcher_content_type_routing():
    """Test content type to extractor mapping."""
    fetcher = URLFetcher()

    assert fetcher.get_extractor_for_content_type("application/pdf") == "pdf"
    assert fetcher.get_extractor_for_content_type("text/html") == "html"
    assert fetcher.get_extractor_for_content_type("text/plain") == "text"
    assert fetcher.get_extractor_for_content_type("application/json") == "json"


def test_connector_item_dataclass():
    """Test ConnectorItem creation."""
    from datetime import datetime

    item = ConnectorItem(
        id="123",
        title="Test Article",
        url="https://example.com/article/123",
        updated_at=datetime.now(),
        content_type="text/html",
        metadata={"draft": False}
    )

    assert item.id == "123"
    assert item.title == "Test Article"


def test_zendesk_connector_type():
    """Test Zendesk connector type."""
    connector = ZendeskConnector(subdomain="test")
    assert connector.get_connector_type() == "zendesk"


def test_zendesk_unauthenticated():
    """Test Zendesk requires authentication."""
    connector = ZendeskConnector(subdomain="test")

    import pytest
    with pytest.raises(RuntimeError, match="Not authenticated"):
        import asyncio
        async def fetch():
            async for _item in connector.fetch_items():
                pass
        asyncio.run(fetch())


@pytest.mark.asyncio
async def test_zendesk_authentication_success():
    """Test Zendesk authentication with valid credentials."""
    connector = ZendeskConnector(subdomain="test")

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = lambda: {"user": {"id": 123, "email": "test@test.com"}}

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_cm

        result = await connector.authenticate({
            "email": "test@test.com",
            "api_token": "fake_token"
        })

        assert result is True
        assert connector._authenticated is True


@pytest.mark.asyncio
async def test_zendesk_authentication_failure():
    """Test Zendesk authentication with invalid credentials."""
    connector = ZendeskConnector(subdomain="test")

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status = MagicMock(side_effect=Exception("401 Unauthorized"))

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_cm

        result = await connector.authenticate({
            "email": "wrong@test.com",
            "api_token": "bad_token"
        })

        assert result is False
        assert connector._authenticated is False


@pytest.mark.asyncio
async def test_zendesk_fetch_items_incremental_sync():
    """Test Zendesk incremental sync with 'since' parameter."""
    from datetime import datetime

    connector = ZendeskConnector(subdomain="test", email="test@test.com", api_token="token")
    connector._authenticated = True  # Skip auth for this test

    since_date = datetime(2024, 1, 1, tzinfo=UTC)

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = lambda: {
            "articles": [
                {
                    "id": 1,
                    "name": "Test Article",
                    "html_url": "https://test.zendesk.com/articles/1",
                    "updated_at": "2024-06-01T12:00:00Z",
                    "section_id": 100,
                    "author_id": 1,
                    "draft": False,
                    "promoted": True,
                    "vote_sum": 10
                }
            ],
            "next_page": None
        }

        mock_get = AsyncMock(return_value=mock_response)
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value.get = mock_get
        mock_client.return_value = mock_cm

        items = []
        async for item in connector.fetch_items(since=since_date):
            items.append(item)

        assert len(items) == 1
        assert items[0].id == "1"
        assert items[0].title == "Test Article"

        # Verify 'since' parameter was passed
        call_args = mock_get.call_args
        assert "updated_after" in call_args.kwargs.get("params", {}) or \
               (call_args.args and "updated_after" in str(call_args))


@pytest.mark.asyncio
async def test_zendesk_fetch_items_pagination():
    """Test Zendesk handles multi-page results."""
    connector = ZendeskConnector(subdomain="test", email="test@test.com", api_token="token")
    connector._authenticated = True

    page1_response = MagicMock()
    page1_response.status_code = 200
    page1_response.raise_for_status = MagicMock()
    page1_response.json = lambda: {
        "articles": [{"id": 1, "name": "Article 1", "html_url": "", "updated_at": "2024-01-01T00:00:00Z"}],
        "next_page": "https://test.zendesk.com/api/v2/help_center/articles.json?page=2"
    }

    page2_response = MagicMock()
    page2_response.status_code = 200
    page2_response.raise_for_status = MagicMock()
    page2_response.json = lambda: {
        "articles": [{"id": 2, "name": "Article 2", "html_url": "", "updated_at": "2024-01-02T00:00:00Z"}],
        "next_page": None
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=[page1_response, page2_response])
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value.get = mock_get
        mock_client.return_value = mock_cm

        items = []
        async for item in connector.fetch_items():
            items.append(item)

        assert len(items) == 2
        assert items[0].id == "1"
        assert items[1].id == "2"
        assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_zendesk_get_item_content():
    """Test fetching individual article content."""
    connector = ZendeskConnector(subdomain="test", email="test@test.com", api_token="token")
    connector._authenticated = True

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = lambda: {
            "article": {
                "id": 123,
                "body": "<h1>Test Content</h1><p>This is the article body.</p>"
            }
        }

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_cm

        content = await connector.get_item_content("123")

        assert b"Test Content" in content
        assert b"article body" in content


@pytest.mark.asyncio
async def test_zendesk_error_handling_rate_limit():
    """Test Zendesk handles 429 rate limit errors."""
    connector = ZendeskConnector(subdomain="test", email="test@test.com", api_token="token")
    connector._authenticated = True

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status = MagicMock(side_effect=Exception("429 Too Many Requests"))

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_cm

        with pytest.raises(Exception, match="429"):
            async for _ in connector.fetch_items():
                pass

