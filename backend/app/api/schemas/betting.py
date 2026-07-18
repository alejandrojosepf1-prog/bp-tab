import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import BetMarketStatus, BetType, PredictionStatus


class BetMarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bet_type: BetType
    label: str
    description: str | None
    opens_at: datetime.datetime
    closes_at: datetime.datetime
    status: BetMarketStatus
    target_round_id: int | None
    target_break_category_id: int | None


class BetMarketCreate(BaseModel):
    bet_type: BetType
    label: str
    description: str | None = None
    opens_at: datetime.datetime
    closes_at: datetime.datetime
    points_rule: dict[str, Any] | None = None
    target_round_id: int | None = None
    target_break_category_id: int | None = None


class BetMarketPatch(BaseModel):
    status: BetMarketStatus | None = None


class SettleRequest(BaseModel):
    manual_outcome: dict[str, Any] | None = None


class SettleResponse(BaseModel):
    settled: bool


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bet_market_id: int
    user_id: int
    payload: dict[str, Any]
    status: PredictionStatus
    # Denominated in fictional USD ("dólares apostados") -- there is no real money anywhere in
    # this platform; it's just the unit the friend group uses to keep score. See
    # `app.domain.scoring` for how each bet_type's payout is computed.
    points_awarded: float | None
    locked_at: datetime.datetime
    created_at: datetime.datetime


class PredictionCreate(BaseModel):
    payload: dict[str, Any]
