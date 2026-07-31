from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    BPPosition,
    DebateStatus,
    JudgeRole,
    MotionCategory,
    RoundStage,
    RoundStatus,
    SpeakerRole,
)
from app.models.mixins import ExternalIdMixin, TimestampMixin, TournamentScopedMixin


class Round(Base, TournamentScopedMixin, TimestampMixin):
    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("tournament_id", "seq", name="uq_rounds_tournament_seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[RoundStage] = mapped_column(default=RoundStage.PRELIMINARY, nullable=False)
    break_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("break_categories.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[RoundStatus] = mapped_column(default=RoundStatus.DRAFT, nullable=False)

    # The round's motion and info slide, mirrored from the tournament's public /motions/ page so
    # bettors can read what's actually being debated without leaving the app for the tab. NULL
    # until that round's motion is released. Deliberately stored on Round rather than on
    # Result.motion_text (which is per-debate and only exists once a ballot is published, i.e.
    # after the debate is over -- useless for anyone deciding a bet).
    motion_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    info_slide: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ground truth for the MOTION_TYPE bet market, loaded by an admin BEFORE the motion is
    # revealed (see app.api.routers.admin's motion-category endpoint) -- deliberately NEVER
    # exposed on the public RoundOut schema, or the market would just be reading the answer off
    # the API. build_market_outcome additionally gates settlement on motion_text being non-null
    # too, so the market can never auto-settle before the motion is actually announced.
    motion_category: Mapped[MotionCategory | None] = mapped_column(nullable=True)

    debates = relationship("Debate", back_populates="round", order_by="Debate.external_id")


class Room(Base, TournamentScopedMixin, TimestampMixin):
    """CalicoTab never exposes a numeric room/venue id publicly (only its free-text name, seen
    on the ballot page header, e.g. 'Sala 14 - A-233'), so the name itself is the natural key."""

    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("tournament_id", "name", name="uq_rooms_tournament_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Debate(Base, TournamentScopedMixin, ExternalIdMixin, TimestampMixin):
    __tablename__ = "debates"
    __table_args__ = (
        UniqueConstraint("tournament_id", "external_id", name="uq_debates_tournament_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[DebateStatus] = mapped_column(default=DebateStatus.DRAFT, nullable=False)

    round = relationship("Round", back_populates="debates")
    room = relationship("Room")
    teams = relationship(
        "DebateTeam",
        back_populates="debate",
        cascade="all, delete-orphan",
        order_by="DebateTeam.position",
    )
    adjudicators = relationship(
        "DebateAdjudicator", back_populates="debate", cascade="all, delete-orphan"
    )
    result = relationship(
        "Result", back_populates="debate", uselist=False, cascade="all, delete-orphan"
    )


class DebateTeam(Base, TimestampMixin):
    """A team's participation in one debate: its BP position and the outcome for that team."""

    __tablename__ = "debate_teams"
    __table_args__ = (
        UniqueConstraint("debate_id", "team_id", name="uq_debate_teams_debate_team"),
        UniqueConstraint("debate_id", "position", name="uq_debate_teams_debate_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(
        ForeignKey("debates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[BPPosition] = mapped_column(nullable=False)

    # Nullable: unknown until the ballot for this debate is confirmed/published.
    rank_in_debate: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1st..4th
    team_points: Mapped[int | None] = mapped_column(Integer, nullable=True)  # BP: 3/2/1/0
    speaker_points_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    advanced: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # elimination rounds only

    debate = relationship("Debate", back_populates="teams")
    team = relationship("Team")
    speaker_scores = relationship(
        "SpeakerScore", back_populates="debate_team", cascade="all, delete-orphan"
    )


class SpeakerScore(Base, TimestampMixin):
    __tablename__ = "speaker_scores"
    __table_args__ = (
        UniqueConstraint("debate_team_id", "role", name="uq_speaker_scores_debate_team_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_team_id: Mapped[int] = mapped_column(
        ForeignKey("debate_teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    speaker_id: Mapped[int] = mapped_column(
        ForeignKey("speakers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[SpeakerRole] = mapped_column(nullable=False)
    # Nullable: many tournaments withhold speaker points until the tournament ends.
    score: Mapped[float | None] = mapped_column(nullable=True)
    is_iron: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    debate_team = relationship("DebateTeam", back_populates="speaker_scores")
    speaker = relationship("Speaker")


class DebateAdjudicator(Base):
    __tablename__ = "debate_adjudicators"
    __table_args__ = (
        UniqueConstraint(
            "debate_id", "adjudicator_id", name="uq_debate_adjudicators_debate_adjudicator"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(
        ForeignKey("debates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    adjudicator_id: Mapped[int] = mapped_column(
        ForeignKey("adjudicators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[JudgeRole] = mapped_column(nullable=False)

    debate = relationship("Debate", back_populates="adjudicators")
    adjudicator = relationship("Adjudicator")


class Result(Base, TimestampMixin):
    """Ballot metadata for a debate. Does NOT duplicate scores — those live on
    DebateTeam/SpeakerScore. This only tracks the motion and confirmation provenance."""

    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(
        ForeignKey("debates.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ballot_source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    motion_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    debate = relationship("Debate", back_populates="result")
