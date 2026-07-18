import datetime

from pydantic import BaseModel, ConfigDict

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


class TournamentCreate(BaseModel):
    name: str
    source_base_url: str
    source_slug: str
    timezone: str = "UTC"


class TournamentUpdate(BaseModel):
    name: str | None = None
    source_base_url: str | None = None
    source_slug: str | None = None
    is_active: bool | None = None


class ScrapeQueuedResponse(BaseModel):
    status: str = "queued"
