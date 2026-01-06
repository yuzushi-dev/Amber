"""
URL Fetcher
===========

Fetches documents from URLs with retry logic and custom headers.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Result of a URL fetch operation."""
    content: bytes
    content_type: str
    final_url: str
    metadata: dict[str, Any]


class URLFetcher:
    """
    Fetches content from URLs with retry logic and custom headers.
    """

    DEFAULT_HEADERS = {
        "User-Agent": "Amber-GraphRAG/1.0 (Document Ingestion)"
    }

    MAX_REDIRECTS = 5
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 1.0  # seconds
    REQUEST_TIMEOUT = 30.0  # seconds
    RATE_LIMIT_DELAY = 0.5  # seconds between requests

    def __init__(self, rate_limit_delay: float = None):
        """
        Initialize URL fetcher.

        Args:
            rate_limit_delay: Delay between requests in seconds.
        """
        self.rate_limit_delay = rate_limit_delay or self.RATE_LIMIT_DELAY
        self._last_request_time = 0

    async def fetch(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = None
    ) -> FetchResult:
        """
        Fetch content from a URL with retry logic.

        Args:
            url: URL to fetch.
            headers: Optional custom headers (Authorization, Cookie, etc.)
            timeout: Request timeout in seconds.

        Returns:
            FetchResult with content and metadata.

        Raises:
            ValueError: For invalid URLs.
            httpx.HTTPError: For unrecoverable HTTP errors.
        """
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL: {url}")

        # Merge headers
        request_headers = {**self.DEFAULT_HEADERS}
        if headers:
            request_headers.update(headers)

        timeout_val = timeout or self.REQUEST_TIMEOUT

        # Retry loop
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                # Apply rate limiting
                await self._apply_rate_limit()

                async with httpx.AsyncClient(
                    follow_redirects=True,
                    max_redirects=self.MAX_REDIRECTS,
                    timeout=timeout_val
                ) as client:
                    response = await client.get(url, headers=request_headers)
                    response.raise_for_status()

                    content = response.content
                    content_type = response.headers.get("content-type", "application/octet-stream")
                    # Clean content type (remove charset etc.)
                    if ";" in content_type:
                        content_type = content_type.split(";")[0].strip()

                    return FetchResult(
                        content=content,
                        content_type=content_type,
                        final_url=str(response.url),
                        metadata={
                            "status_code": response.status_code,
                            "content_length": len(content),
                            "content_hash": hashlib.sha256(content).hexdigest(),
                            "response_headers": dict(response.headers),
                        }
                    )

            except httpx.HTTPStatusError as e:
                # Don't retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    logger.error(f"Client error fetching {url}: {e.response.status_code}")
                    raise
                last_error = e

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e

            except Exception as e:
                last_error = e

            # Calculate backoff delay
            delay = self.RETRY_DELAY_BASE * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed for {url}, retrying in {delay}s: {last_error}")
            await asyncio.sleep(delay)

        # All retries exhausted
        logger.error(f"All retries exhausted for {url}")
        raise last_error or Exception(f"Failed to fetch {url}")

    async def _apply_rate_limit(self):
        """Apply rate limiting between requests."""
        import time
        now = time.time()
        elapsed = now - self._last_request_time

        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)

        self._last_request_time = time.time()

    def get_extractor_for_content_type(self, content_type: str) -> str:
        """
        Determine the appropriate extractor based on content type.

        Returns:
            Extractor name: 'pdf', 'html', 'text', etc.
        """
        content_type = content_type.lower()

        if "pdf" in content_type:
            return "pdf"
        elif "html" in content_type:
            return "html"
        elif "text/plain" in content_type:
            return "text"
        elif "word" in content_type or "docx" in content_type:
            return "docx"
        elif "json" in content_type:
            return "json"
        else:
            return "unknown"
