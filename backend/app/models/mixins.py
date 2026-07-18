import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class TimestampMixin:
    """created_at / updated_at columns, maintained by the database itself."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TournamentScopedMixin:
    """Every tournament-owned entity carries a non-nullable tournament_id.

    This is what makes the schema multi-tenant by construction rather than by convention:
    every natural-key unique constraint in this codebase includes tournament_id, so two
    tournaments can never collide even if the source site reuses external ids.
    """

    @declared_attr
    def tournament_id(cls) -> Mapped[int]:
        return mapped_column(
            ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
        )


class ExternalIdMixin:
    """The numeric id CalicoTab/Tabbycat exposes in its own URLs (e.g. .../team/259915/).

    Used as the natural key for idempotent upserts: (tournament_id, external_id) uniquely
    identifies a row regardless of how many times the scraper re-fetches it.
    """

    external_id: Mapped[int] = mapped_column(nullable=False, index=True)
