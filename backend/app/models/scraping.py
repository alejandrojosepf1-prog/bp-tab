import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ChangeType, ScrapeStatus, ScrapeStrategy
from app.models.mixins import TournamentScopedMixin


class ScrapeLog(Base, TournamentScopedMixin):
    """One row per scrape run. Feeds the admin 'Ver logs' screen and the scraper's own
    idempotency bookkeeping (what was fetched, what changed, how long it took)."""

    __tablename__ = "scrape_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[ScrapeStatus] = mapped_column(default=ScrapeStatus.SUCCESS, nullable=False)
    strategy_used: Mapped[ScrapeStrategy] = mapped_column(nullable=False)

    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entities_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entities_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChangeEvent(Base, TournamentScopedMixin):
    """A single detected change from one scrape cycle to the next. Powers the dashboard's
    'cambios recientes' feed. Only written when a field value actually differs — the upsert
    layer never writes a ChangeEvent for a no-op re-fetch."""

    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[ChangeType] = mapped_column(nullable=False)
    field_diff: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    round_id: Mapped[int | None] = mapped_column(
        ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True
    )
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
