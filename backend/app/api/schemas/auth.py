import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    # Fictional USD bankroll -- see app.models.betting.User.balance.
    balance: float
    created_at: datetime.datetime


class MyPredictionOut(BaseModel):
    """A user's prediction joined with enough market/tournament context to render a bet
    history without extra round-trips."""

    id: int
    bet_market_id: int
    market_label: str
    bet_type: str
    market_status: str
    tournament_id: int
    tournament_name: str
    # Human-readable description of what was picked, e.g. "Marce Gómez — 2º" or
    # "Ceviche de Falacias → Mystical Poke → ..." -- see
    # app.services.odds_service.format_payload_label. Replaces rendering raw payload fields
    # (which used to show as a bare "@" odds suffix with no selection context).
    selection_label: str
    status: str
    stake_amount: float
    odds: float
    potential_payout: float
    points_awarded: float | None
    # Optional modular sub-bet layered on this same prediction -- see
    # app.models.betting.Prediction's sub_bet_* column docstring. sub_bet_status is None when
    # no sub-bet was placed at all.
    sub_bet_odds: float | None = None
    sub_bet_status: str | None = None
    sub_bet_points_awarded: float | None = None
    created_at: datetime.datetime


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
