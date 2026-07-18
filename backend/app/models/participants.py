from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import ExternalIdMixin, TimestampMixin, TournamentScopedMixin


class Institution(Base, TournamentScopedMixin, TimestampMixin):
    """Institutions have no public detail page / numeric id on CalicoTab (unlike teams and
    adjudicators), so the natural key is the short institution code CalicoTab always shows
    on its institutions list (e.g. 'PUCP'), not an ExternalIdMixin-style numeric id."""

    __tablename__ = "institutions"
    __table_args__ = (
        UniqueConstraint("tournament_id", "code", name="uq_institutions_tournament_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Sourced from CalicoTab's institutions list "Region" column, which in Latin American BP
    # circuits is populated with the country name (verified against the CMUDE 2025 fixture:
    # 'Chile', 'Perú', 'España', ...). Kept nullable/free-text since not every tournament fills
    # it in, and some may use it for a sub-national region instead of a country.
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)

    teams = relationship("Team", back_populates="institution")
    adjudicators = relationship("Adjudicator", back_populates="institution")


class BreakCategory(Base, TournamentScopedMixin, TimestampMixin):
    """A team-level break category, e.g. Open / ESL / Novice (when the tournament breaks
    those categories as teams, as opposed to speaker-only awards — see SpeakerCategory)."""

    __tablename__ = "break_categories"
    __table_args__ = (
        UniqueConstraint("tournament_id", "slug", name="uq_break_categories_tournament_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    is_general: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    break_size: Mapped[int | None] = mapped_column(nullable=True)


class SpeakerCategory(Base, TournamentScopedMixin, TimestampMixin):
    """A speaker-level award/eligibility category, e.g. ESL / Novice / EFL speaker tabs."""

    __tablename__ = "speaker_categories"
    __table_args__ = (
        UniqueConstraint("tournament_id", "slug", name="uq_speaker_categories_tournament_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)


class Team(Base, TournamentScopedMixin, ExternalIdMixin, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("tournament_id", "external_id", name="uq_teams_tournament_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True
    )

    institution = relationship("Institution", back_populates="teams")
    speakers = relationship("Speaker", back_populates="team", order_by="Speaker.name")
    break_categories = relationship(
        "BreakCategory", secondary="team_break_categories", backref="teams"
    )


class TeamBreakCategory(Base):
    """Many-to-many: which break categories a team is eligible/registered for."""

    __tablename__ = "team_break_categories"

    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    break_category_id: Mapped[int] = mapped_column(
        ForeignKey("break_categories.id", ondelete="CASCADE"), primary_key=True
    )


class Speaker(Base, TournamentScopedMixin, TimestampMixin):
    """CalicoTab never exposes a numeric id or detail link for individual speakers (only
    teams and adjudicators get one) when scraped via HTML/vueData, so the natural key here
    is (team, name) rather than an external id. ``external_id`` is kept as an optional column,
    populated only when a tournament's DRF API is available and does expose real speaker ids."""

    __tablename__ = "speakers"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "team_id", "name", name="uq_speakers_tournament_team_name"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    team = relationship("Team", back_populates="speakers")
    categories = relationship(
        "SpeakerCategory", secondary="speaker_category_links", backref="speakers"
    )


class SpeakerCategoryLink(Base):
    __tablename__ = "speaker_category_links"

    speaker_id: Mapped[int] = mapped_column(
        ForeignKey("speakers.id", ondelete="CASCADE"), primary_key=True
    )
    speaker_category_id: Mapped[int] = mapped_column(
        ForeignKey("speaker_categories.id", ondelete="CASCADE"), primary_key=True
    )


class Adjudicator(Base, TournamentScopedMixin, ExternalIdMixin, TimestampMixin):
    __tablename__ = "adjudicators"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "external_id", name="uq_adjudicators_tournament_external"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True
    )
    is_independent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    institution = relationship("Institution", back_populates="adjudicators")
