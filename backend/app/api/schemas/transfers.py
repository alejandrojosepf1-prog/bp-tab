import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import TransactionType


class TransferCreate(BaseModel):
    recipient_id: int
    amount: float
    # Which tournament's TournamentBalance to move the tokens within (CNADE 2026 Roadmap
    # Pieza 3 -- balance is per-tournament, there's no tournament-less transfer anymore).
    tournament_id: int
    note: str | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: TransactionType
    amount: float
    balance_after: float
    note: str | None
    counterparty_user_id: int | None
    # Filled in by the router from a joined User lookup -- not a real column, same pattern as
    # BetMarketOut.pool_total.
    counterparty_display_name: str | None = None
    created_at: datetime.datetime


class TransferOut(BaseModel):
    sent: TransactionOut
