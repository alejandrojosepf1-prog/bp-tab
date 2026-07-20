import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
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

    BigInteger rather than the default 32-bit Integer: real Tabbycat ids are always small, but
    `Debate.external_id` (the only user of this mixin with a non-Tabbycat-sourced id) sometimes
    holds a synthesized pseudo-id derived from `zlib.crc32(...)` for elimination-round debates
    published without a public ballot (see `_synthetic_debate_id` in scraper/parsers.py) --
    crc32's full unsigned 32-bit output range exceeds Postgres's signed int32 max
    (2147483647) and was silently accepted by SQLite's dynamic typing in local dev, only
    surfacing as `DataError: value out of int32 range` once run against real Postgres.
    """

    external_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
