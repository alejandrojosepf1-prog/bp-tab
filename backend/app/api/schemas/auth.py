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
    status: str
    stake_amount: float
    odds: float
    potential_payout: float
    points_awarded: float | None
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
