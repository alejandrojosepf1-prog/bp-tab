import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.api.schemas.betting import BetMarketOut, PredictionOut
from app.api.schemas.leaderboard import LeaderboardEntryOut
from app.api.schemas.rounds import RoundOut
from app.models.enums import ChangeType


class ChangeEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: str
    entity_id: int
    change_type: ChangeType
    field_diff: dict[str, Any]
    round_id: int | None
    detected_at: datetime.datetime


class DashboardOut(BaseModel):
    latest_round: RoundOut | None
    recent_changes: list[ChangeEventOut]
    leaderboard_top: list[LeaderboardEntryOut]
    my_predictions: list[PredictionOut] | None
    open_bet_markets: list[BetMarketOut]
