import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import BetMarketStatus, BetType, PredictionStatus, UserRole
from app.models.mixins import TimestampMixin, TournamentScopedMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[UserRole] = mapped_column(default=UserRole.USER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Fictional USD bankroll -- goes up and down as the user places/wins/loses bets (see
    # services/betting_service.py). STARTING_BALANCE is the one-time grant a brand new user
    # gets; there is no real money anywhere in this platform.
    balance: Mapped[float] = mapped_column(Float, default=1000.0, nullable=False)


class BetMarket(Base, TournamentScopedMixin, TimestampMixin):
    """A prediction question the admin opens up, e.g. 'Who will be Champion?'. Individual
    user answers are recorded as Prediction rows against this market."""

    __tablename__ = "bet_markets"

    id: Mapped[int] = mapped_column(primary_key=True)
    bet_type: Mapped[BetType] = mapped_column(nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    target_round_id: Mapped[int | None] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), nullable=True
    )
    target_break_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("break_categories.id", ondelete="CASCADE"), nullable=True
    )

    opens_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    points_rule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[BetMarketStatus] = mapped_column(default=BetMarketStatus.OPEN, nullable=False)
    settled_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    predictions = relationship(
        "Prediction", back_populates="bet_market", cascade="all, delete-orphan"
    )


class Prediction(Base, TimestampMixin):
    """A single user's answer to a BetMarket. Frozen at creation time via locked_at so a later
    edit to the market's closing time can't retroactively affect an already-placed bet.

    A user can hold more than one OPEN prediction on the same market, as long as each one
    targets a different `entity_key` -- e.g. a different debate within a round-scoped market,
    a different top-3 position, or a different team in an independent team_break market.
    Re-submitting the SAME entity_key still edits/replaces that one prediction (refunding its
    prior stake), matching a real sportsbook's "one open position per selection" rule rather
    than "one bet per market" (see app.services.betting_service._entity_key)."""

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "bet_market_id", "user_id", "entity_key", name="uq_predictions_market_user_entity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bet_market_id: Mapped[int] = mapped_column(
        ForeignKey("bet_markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # What this prediction competes against for uniqueness within (bet_market_id, user_id) --
    # "__market__" for single-choice bet types (champion, best_institution, ...), else a
    # payload-derived key (e.g. "debate:123", "position:2", "team:45") so a user can hold one
    # open prediction PER debate/position/team instead of one per market. See
    # app.services.betting_service._entity_key -- the single source of truth for this value.
    entity_key: Mapped[str] = mapped_column(String(64), nullable=False)

    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    locked_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[PredictionStatus] = mapped_column(default=PredictionStatus.OPEN, nullable=False)
    # Fictional USD wagered on this specific prediction, deducted from User.balance the moment
    # it's placed (see services/betting_service.py::place_prediction).
    stake_amount: Mapped[float] = mapped_column(Float, nullable=False)
    # Decimal ("pays 1.85x") odds, priced from team/speaker/institution strength by
    # app.services.odds_service at the moment this prediction was placed and frozen from then
    # on -- a later swing in the market's pool or in team strength never changes an
    # already-placed bet's payout, same as a real fixed-odds sportsbook (not pari-mutuel).
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    # The actual amount credited back to User.balance once settled: stake_amount * odds if this
    # prediction won, 0.0 if it lost, None while still OPEN. (Field predates the odds/stake
    # model -- kept under its original name since it's the same "how much did this prediction
    # pay" concept, just no longer a fixed per-bet_type point value.)
    points_awarded: Mapped[float | None] = mapped_column(Float, nullable=True)

    bet_market = relationship("BetMarket", back_populates="predictions")
    user = relationship("User")


class LeaderboardEntry(Base, TimestampMixin):
    """Read-optimized aggregate, rewritten wholesale by the settlement service after every
    scoring run. Never hand-edited — this is a materialized view of Prediction.points_awarded,
    not a second source of truth."""

    __tablename__ = "leaderboard_entries"
    __table_args__ = (
        UniqueConstraint("tournament_id", "user_id", name="uq_leaderboard_tournament_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    total_points: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user = relationship("User")
