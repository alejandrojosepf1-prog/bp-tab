import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import PrizeEventStatus, PrizeEventType
from app.models.mixins import TimestampMixin, TournamentScopedMixin


class PrizeEvent(Base, TournamentScopedMixin, TimestampMixin):
    """An admin-run token giveaway, independent of betting outcomes -- see
    app.services.prize_service's module docstring for how each `type` resolves.

    Lifecycle is one-way, OPEN -> RESOLVED, mirroring how a settled BetMarket never reopens:
    once resolved, an event's entries/payouts are permanent history, not something to redo.
    """

    __tablename__ = "prize_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[PrizeEventType] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PrizeEventStatus] = mapped_column(
        default=PrizeEventStatus.OPEN, nullable=False
    )
    # Type-specific knobs -- see app.services.prize_service for the shape each type reads:
    #   raffle: {"num_winners": int, "prize_per_winner": float, "ticket_cost": float | None}
    #   activity_bonus: {"bonus_amount": float}
    #   manual_award: {} (each entry carries its own amount instead of a shared config)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # raffle: entry deadline. activity_bonus: end of the qualifying window (falls back to "now"
    # at resolve time if left unset). manual_award: unused, always null.
    closes_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The exact seed used to draw raffle winners, persisted once resolved so the draw is
    # independently reproducible from this row alone -- nobody has to take the admin's word for
    # who won. Null for the other two types (nothing random about them).
    rng_seed: Mapped[str | None] = mapped_column(String(100), nullable=True)

    entries = relationship(
        "PrizeEntry", back_populates="prize_event", cascade="all, delete-orphan"
    )


class PrizeEntry(Base, TimestampMixin):
    """One user's stake in a PrizeEvent. What the columns mean depends on the event's type:

    - manual_award: one row per awarded user, `awarded_amount` set at creation time (the admin
      picks the amount up front) and credited the moment the event resolves.
    - raffle: one row per entrant, `tickets` is how many they bought; `awarded_amount` stays
      null until resolution, then holds what that entry actually won (0 for non-winners, so
      "did I win" is always answerable from this same row without a separate winners list).
    - activity_bonus: rows are created BY the resolve step itself (not by users entering) for
      every user who qualified, with `awarded_amount` set to the flat bonus immediately.
    """

    __tablename__ = "prize_entries"
    __table_args__ = (
        UniqueConstraint("prize_event_id", "user_id", name="uq_prize_entries_event_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    prize_event_id: Mapped[int] = mapped_column(
        ForeignKey("prize_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tickets: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    awarded_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    prize_event = relationship("PrizeEvent", back_populates="entries")
    user = relationship("User")
