import datetime

from pydantic import BaseModel, ConfigDict

from app.api.schemas.auth import UserOut
from app.models.enums import PrizeEventStatus, PrizeEventType


class PrizeEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserOut
    tickets: int
    awarded_amount: float | None


class PrizeEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tournament_id: int
    type: PrizeEventType
    title: str
    description: str | None
    status: PrizeEventStatus
    config: dict
    closes_at: datetime.datetime | None
    resolved_at: datetime.datetime | None
    rng_seed: str | None
    # Computed by the router, not columns -- lets the "Premios" tab show entry counts without a
    # second round-trip per event.
    entry_count: int = 0
    total_tickets: int = 0


class PrizeEventDetailOut(PrizeEventOut):
    entries: list[PrizeEntryOut] = []


class PrizeEventCreate(BaseModel):
    type: PrizeEventType
    title: str
    description: str | None = None
    # See PrizeEvent.config's docstring for the shape each type expects. Validated at the
    # service layer (queue_manual_award / enter_raffle / resolve reads config.get(...) with
    # defaults), not here -- keeping creation permissive means a raffle's config can be filled
    # in progressively as the admin queues awards, same as the rest of this admin panel.
    config: dict = {}
    closes_at: datetime.datetime | None = None


class ManualAwardQueue(BaseModel):
    user_id: int
    amount: float


class RaffleEntryIn(BaseModel):
    tickets: int = 1
