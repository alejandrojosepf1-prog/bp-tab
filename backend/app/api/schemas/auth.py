import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime.datetime


class MeUpdate(BaseModel):
    """Self-service profile edit. Deliberately display_name ONLY -- email is the login identity
    and role/is_active are admin-controlled (PATCH /admin/users/{id}); balance isn't editable
    anywhere (it's derived from TournamentBalance -- see GET /tournaments/{id}/me/balance)."""

    display_name: str = Field(min_length=2, max_length=100)


class UserSummaryOut(BaseModel):
    """Minimal, low-privacy-risk view of another user -- id + display name only, no email/role/
    balance. Backs the P2P transfer recipient picker (GET /auth/users): every authenticated user
    can see who else is on this private, friends-only platform, but not their wallet or account
    details (that's UserOut, admin-only via GET /admin/users)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str


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
