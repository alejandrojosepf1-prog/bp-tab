import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import TransactionType


class TransferCreate(BaseModel):
    recipient_id: int
    amount: float
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
