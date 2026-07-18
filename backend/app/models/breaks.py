from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import BreakStatus
from app.models.mixins import TimestampMixin, TournamentScopedMixin


class Break(Base, TournamentScopedMixin, TimestampMixin):
    """The OFFICIAL break as published by CalicoTab. Never mixed with our own predictions —
    see BreakPrediction for that. The dashboard always prefers this table when a row exists."""

    __tablename__ = "breaks"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "break_category_id", "team_id", name="uq_breaks_category_team"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    break_category_id: Mapped[int] = mapped_column(
        ForeignKey("break_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[BreakStatus] = mapped_column(default=BreakStatus.CONFIRMED, nullable=False)
    confirmed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)


class BreakPrediction(Base, TournamentScopedMixin, TimestampMixin):
    """Our own system-computed break projection, recorded once per round so history is kept
    (never overwritten) — see domain.break_predictor for the algorithm that populates this."""

    __tablename__ = "break_predictions"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "break_category_id",
            "team_id",
            "as_of_round_id",
            name="uq_break_predictions_category_team_round",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    break_category_id: Mapped[int] = mapped_column(
        ForeignKey("break_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    as_of_round_id: Mapped[int] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False)  # safe / alive / eliminated
    probability: Mapped[float] = mapped_column(nullable=False)
    projected_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points_needed: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    team = relationship("Team")


class AdjudicatorBreak(Base, TournamentScopedMixin, TimestampMixin):
    __tablename__ = "adjudicator_breaks"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "adjudicator_id", name="uq_adjudicator_breaks_tournament_adjudicator"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    adjudicator_id: Mapped[int] = mapped_column(
        ForeignKey("adjudicators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confirmed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
