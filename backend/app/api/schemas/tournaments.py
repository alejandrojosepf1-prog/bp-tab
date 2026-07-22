import datetime

from pydantic import BaseModel, ConfigDict

from app.api.schemas.rounds import RoundOut
from app.models.enums import TournamentStatus


class TournamentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    source_base_url: str
    source_slug: str
    status: TournamentStatus
    api_available: bool
    champion_team_id: int | None
    timezone: str
    is_active: bool
    created_at: datetime.datetime
    # Card-level summary for the dashboard (filled by the list/get endpoints, not columns):
    # lets the tournament cards show "ronda actual", team count and open-market count without
    # extra round-trips per tournament.
    current_round: RoundOut | None = None
    teams_count: int = 0
    open_markets_count: int = 0


class TournamentCreate(BaseModel):
    name: str
    # A single pasted CalicoTab tab URL, e.g.
    # "https://cmude2025.calicotab.com/open/participants/list/" -- the router derives
    # source_base_url/source_slug from it via app.domain.tab_url.parse_tab_url, instead of
    # asking the admin to split the URL into two fields by hand.
    tab_url: str
    timezone: str = "UTC"


class TournamentUpdate(BaseModel):
    name: str | None = None
    tab_url: str | None = None
    is_active: bool | None = None


class ScrapeQueuedResponse(BaseModel):
    status: str = "queued"
