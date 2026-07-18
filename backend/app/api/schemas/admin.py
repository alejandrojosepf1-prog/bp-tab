import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ScrapeStatus, ScrapeStrategy, UserRole


class ScrapeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    status: ScrapeStatus
    strategy_used: ScrapeStrategy
    pages_fetched: int
    entities_created: int
    entities_updated: int
    error_message: str | None


class AdminUserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
