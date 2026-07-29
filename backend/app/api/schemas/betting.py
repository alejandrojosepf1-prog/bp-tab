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
    # Sum of every stake placed on this market so far, in fictional USD, and how many distinct
    # users have staked. Under pari-mutuel-with-seed pricing (see app.domain.odds) the open
    # pool DOES feed back into quoted odds. Both are computed by the router, not columns.
    pool_total: float = 0.0
    bettors_count: int = 0


class MarketBoardOptionOut(BaseModel):
    key: str
    label: str
    emoji: str | None
    stake: float
    backers: int
    odds: float


class MarketBoardOut(BaseModel):
    market: BetMarketOut
    pool_total: float
    bettors: int
    options: list[MarketBoardOptionOut]


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
    # Required when reopening a market whose closes_at is already in the past (see
    # betting_service.set_bet_market_status) -- otherwise the just-reopened market immediately
    # rejects every prediction again since `now >= closes_at` still holds. Can also be sent
    # on its own, with no status change, to simply push a still-open market's deadline back.
    closes_at: datetime.datetime | None = None


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
    # All amounts denominated in fictional USD ("dólares apostados") -- there is no real money
    # anywhere in this platform. Odds are fixed (sportsbook-style), priced from team/speaker/
    # institution strength by app.services.odds_service and frozen at the moment this
    # prediction was placed -- see app.domain.odds's module docstring.
    stake_amount: float
    odds: float
    # stake_amount * odds -- what this prediction would pay out if it wins. Always known (the
    # odds are locked at placement), unlike points_awarded which stays None until settled.
    # Not a real column -- computed and overwritten by the router (see _to_prediction_out); the
    # default here only exists so model_validate(ORM instance) doesn't fail looking for it.
    potential_payout: float = 0.0
    # The amount actually credited back once settled: stake_amount * odds if won, 0.0 if lost,
    # None while still OPEN.
    points_awarded: float | None
    # Optional modular sub-bet layered on this same prediction (e.g. an exact rank gap or exact
    # speaker points) -- see app.models.betting.Prediction's sub_bet_* column docstring.
    # sub_bet_status is None when no sub-bet was placed at all.
    sub_bet_odds: float | None = None
    sub_bet_status: PredictionStatus | None = None
    sub_bet_points_awarded: float | None = None
    locked_at: datetime.datetime
    created_at: datetime.datetime


class PredictionCreate(BaseModel):
    payload: dict[str, Any]
    stake_amount: float


class OddsQuoteRequest(BaseModel):
    payload: dict[str, Any]


class OddsQuoteOut(BaseModel):
    odds: float
    # Priced only when payload has a "sub_bet" key and this bet_type supports one -- see
    # app.services.odds_service.quote_sub_bet_odds. None otherwise.
    sub_bet_odds: float | None = None
