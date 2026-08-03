from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import TournamentStatus
from app.models.mixins import TimestampMixin


class Tournament(Base, TimestampMixin):
    """A single tracked tournament.

    The external identity of a tournament is (source_base_url, source_slug) — NOT the domain
    alone, since one CalicoTab deployment can host several tournaments as sibling paths
    (e.g. cmude2025.calicotab.com/open/, /masters/, /discursos/ are three different tournaments
    on one domain). Pointing this platform at a new tournament is purely a data change: insert
    a new Tournament row with a different base URL / slug, no code changes required.
    """

    __tablename__ = "tournaments"
    __table_args__ = (
        UniqueConstraint("source_base_url", "source_slug", name="uq_tournaments_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    # Nullable, admin-set (backfilled tournaments set it explicitly at creation) -- NOT derived
    # from created_at, which is scrape/insert time and would show every backfilled historical
    # tournament as "this year." Used to browse the public archive by year.
    year: Mapped[int | None] = mapped_column(nullable=True)

    source_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_slug: Mapped[str] = mapped_column(String(200), nullable=False)

    status: Mapped[TournamentStatus] = mapped_column(
        default=TournamentStatus.UPCOMING, nullable=False
    )
    api_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    api_last_checked_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    champion_team_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "teams.id", ondelete="SET NULL", use_alter=True, name="fk_tournaments_champion_team"
        ),
        nullable=True,
    )

    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # CNADE 2026 Roadmap Pieza 4 -- admin-toggled per tournament, default off so existing/trial
    # tournaments are unaffected. When True, `place_prediction` requires an APPROVED
    # app.models.access.AccessPass for the tournament, and blocks a matched participant even
    # with one -- see access_pass_service.
    requires_access_pass: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    champion_team = relationship("Team", foreign_keys=[champion_team_id], post_update=True)

    @property
    def source_url_prefix(self) -> str:
        """Base URL to prepend to every scraped path, e.g. https://host.com/open."""
        return f"{self.source_base_url.rstrip('/')}/{self.source_slug.strip('/')}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Tournament id={self.id} slug={self.slug!r} status={self.status}>"
