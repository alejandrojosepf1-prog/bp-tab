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

# One-time grant of play tokens every new account starts with. Claim is a for-fun platform --
# these are not dollars, are never bought or cashed out, and no real money exists anywhere in the
# system. The constant is referenced by the register endpoint and the balance column default so
# the two can never drift apart.
STARTING_BALANCE = 100.0


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[UserRole] = mapped_column(default=UserRole.USER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Play-token balance -- goes up and down as the user places/wins/loses bets (see
    # services/betting_service.py). Every new account is granted STARTING_BALANCE tokens.
    balance: Mapped[float] = mapped_column(Float, default=STARTING_BALANCE, nullable=False)


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
    # The total amount ever credited back to User.balance for this prediction: stake_amount *
    # odds if it won, 0.0 if it lost, None while still OPEN. (Field predates the odds/stake
    # model -- kept under its original name since it's the same "how much did this prediction
    # pay" concept, just no longer a fixed per-bet_type point value.) For round_winner's
    # deferred speaker-points sub-bet specifically, `settle_pending_sub_bets` ADDS its bonus on
    # top of this value later, once the sub-bet resolves -- see sub_bet_points_awarded below for
    # that bonus broken out on its own.
    points_awarded: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Optional sub-bet (modular "apuesta específica" modifier) -------------------------
    # A sub-bet is an extra, harder pick layered onto this SAME prediction (e.g. the exact rank
    # gap in a head-to-head, or the winning team's exact speaker points) -- never a separate
    # market or a separate Prediction row, per the product decision behind this feature. The
    # modifier detail itself lives in `payload["sub_bet"]` (shape is bet_type-specific, same
    # convention as the rest of `payload`); these three columns exist because the sub-bet needs
    # its OWN independent lifecycle, distinct from the base pick's `odds`/`status`/
    # `points_awarded` above:
    #   - For same-timing markets (e.g. round_head_to_head's rank-gap, team_break's exact
    #     rank/points), base and sub-bet settle together, all-or-nothing: missing the modifier
    #     zeroes out `points_awarded` too, exactly like missing any leg of a parlay.
    #   - For round_winner's speaker-points sub-bet specifically, the base pick pays on its own
    #     as soon as the round result is known; the sub-bet can stay open for a long time after
    #     (speaker points are often withheld until the tournament's final tab), settling later
    #     via `betting_service.settle_pending_sub_bets` and crediting an ADDITIONAL bonus on
    #     top of the base payout that already happened -- never retroactively touching it.
    # See app.services.betting_service for exactly which rule applies to which bet_type.
    sub_bet_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # None: this prediction has no sub-bet at all. OPEN: a sub-bet was placed and is awaiting
    # its own resolution. SETTLED: resolved (won or lost) -- see sub_bet_points_awarded.
    sub_bet_status: Mapped[PredictionStatus | None] = mapped_column(nullable=True)
    sub_bet_points_awarded: Mapped[float | None] = mapped_column(Float, nullable=True)

    bet_market = relationship("BetMarket", back_populates="predictions")
    user = relationship("User")


class OddsSnapshot(Base):
    """One captured odds reading for one option of one BetMarket, written on a fixed cadence by
    `app.services.odds_service.capture_odds_snapshot` (called once per autoscrape cycle -- see
    `app.tasks.autoscrape` -- NOT on every board/quote request, which would snapshot on every
    page load instead of on a steady clock). Pure history for the "evolución de cuotas" chart;
    never read by pricing or settlement, so it's safe to prune/ignore without affecting the app.
    `option_key` matches `MarketBoardOption.key` from `odds_service.market_board`."""

    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    bet_market_id: Mapped[int] = mapped_column(
        ForeignKey("bet_markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    option_key: Mapped[str] = mapped_column(String(120), nullable=False)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    captured_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


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
