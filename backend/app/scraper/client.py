import asyncio
import time

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.scraper.exceptions import PageNotAvailableError, ScraperError

settings = get_settings()


class CalicoTabClient:
    """Thin, polite HTTP client for a single tournament's CalicoTab pages.

    Deliberately dumb: it knows nothing about Tabbycat's page structure (that's `parsers.py`'s
    job) -- it only fetches text and turns HTTP-level failure modes into the right exception
    (403/404 -> "not published yet", anything else -> retried, then raised).
    """

    def __init__(self, base_url: str, *, min_delay_seconds: float | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._min_delay = (
            min_delay_seconds
            if min_delay_seconds is not None
            else settings.scraper_min_delay_seconds
        )
        self._last_request_at: float | None = None
        self._client = httpx.AsyncClient(
            timeout=settings.scraper_request_timeout_seconds,
            headers={"User-Agent": settings.scraper_user_agent},
            follow_redirects=True,
        )

    async def __aenter__(self) -> "CalicoTabClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._min_delay - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def get_text(self, path: str) -> str:
        """Fetch `path` (relative to this tournament's base URL) and return the response body.

        Raises `PageNotAvailableError` for 403/404 (the organizer hasn't published this page
        yet -- callers should treat that as "no data", not a scrape failure) and `ScraperError`
        for any other non-2xx status after the transport-level retry policy is exhausted.
        """
        await self._throttle()
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = await self._client.get(url)
        finally:
            self._last_request_at = time.monotonic()

        if response.status_code in (403, 404):
            raise PageNotAvailableError(url, response.status_code)
        if response.status_code >= 400:
            raise ScraperError(f"GET {url} failed with status {response.status_code}")
        return response.text
