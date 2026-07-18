"""Best-effort adapter for Tabbycat's own DRF REST API.

IMPORTANT — unlike every other module in this package, this adapter has NOT been verified
against a live Tabbycat instance: the reference tournament used throughout this project's
development (CMUDE 2025 on CalicoTab) does not have its public API enabled (`/api/v1/` and
`/api/v1/tournaments/` both return 404 -- confirmed during architecture research), which is
common: Tabbycat's anonymous read-only API mode must be explicitly turned on per-tournament by
the organizer, and most don't. This module exists so that a tournament which *does* expose it
gets a faster, more reliable path automatically (see `probe_api_availability`), built strictly
from Tabbycat's published API documentation. Treat it as unverified until it has been exercised
against a real API-enabled tournament, and prefer the vueData/HTML path (`parsers.py`) -- which
*is* fully verified -- whenever in doubt.
"""

from typing import Any

from app.scraper.client import CalicoTabClient


async def probe_api_availability(client: CalicoTabClient, tournament_slug: str) -> bool:
    """GET the tournament's API root once; return True only on a clean 200 + JSON body.

    Called once per tournament per scrape cycle (cheap) so that an organizer enabling the API
    mid-tournament is picked up automatically without any code change or redeploy.
    """
    try:
        text = await client.get_text(f"/api/v1/tournaments/{tournament_slug}/")
    except Exception:
        return False
    try:
        import json

        data = json.loads(text)
    except ValueError:
        return False
    return isinstance(data, dict) and "slug" in data


class TabbycatApiSource:
    """Fetches teams/speakers/institutions/rounds from Tabbycat's DRF API when available.

    Field names follow Tabbycat's published API schema (see /api/schema/redoc/ on any
    API-enabled instance). Not covered by the fixture-based test suite for the reason
    explained in the module docstring -- validate against a real instance before depending
    on this path in production.
    """

    def __init__(self, client: CalicoTabClient, tournament_slug: str) -> None:
        self._client = client
        self._slug = tournament_slug

    async def _get_json(self, path: str) -> Any:
        text = await self._client.get_text(path)
        import json

        return json.loads(text)

    async def fetch_institutions(self) -> list[dict]:
        return await self._get_json(f"/api/v1/tournaments/{self._slug}/institutions")

    async def fetch_teams(self) -> list[dict]:
        return await self._get_json(f"/api/v1/tournaments/{self._slug}/teams")

    async def fetch_rounds(self) -> list[dict]:
        return await self._get_json(f"/api/v1/tournaments/{self._slug}/rounds")
