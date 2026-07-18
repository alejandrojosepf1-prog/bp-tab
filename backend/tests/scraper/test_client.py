import pytest

from app.scraper.client import CalicoTabClient
from app.scraper.exceptions import PageNotAvailableError, ScraperError

BASE_URL = "https://fake.calicotab.com"


@pytest.mark.asyncio
async def test_get_text_returns_body_on_success(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/open/participants/list/", text="<html>ok</html>")
    client = CalicoTabClient(BASE_URL, min_delay_seconds=0)
    try:
        text = await client.get_text("/open/participants/list/")
    finally:
        await client.close()
    assert text == "<html>ok</html>"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 404])
async def test_get_text_raises_page_not_available_on_403_404(httpx_mock, status_code) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/open/draw/round/13/", status_code=status_code)
    client = CalicoTabClient(BASE_URL, min_delay_seconds=0)
    try:
        with pytest.raises(PageNotAvailableError) as exc_info:
            await client.get_text("/open/draw/round/13/")
    finally:
        await client.close()
    assert exc_info.value.status_code == status_code


@pytest.mark.asyncio
async def test_get_text_raises_scraper_error_on_server_error(httpx_mock) -> None:
    # A plain HTTP 5xx response isn't a transport-level failure, so the tenacity retry (which
    # only fires on connection/transport errors) doesn't apply here -- it's just one request.
    httpx_mock.add_response(url=f"{BASE_URL}/open/tab/team/", status_code=500)
    client = CalicoTabClient(BASE_URL, min_delay_seconds=0)
    try:
        with pytest.raises(ScraperError):
            await client.get_text("/open/tab/team/")
    finally:
        await client.close()
