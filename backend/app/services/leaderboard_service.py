"""Bettor rankings -- both the per-tournament view and the cross-tournament "Ranking" tab.

Computed LIVE, directly from `Prediction` rows (net profit = payout minus stake, summed across
every SETTLED prediction), every time someone asks -- the same ground truth
`GET /auth/me/predictions` already sums client-side for a single user's own "Neto liquidado".

This deliberately does NOT read `LeaderboardEntry` (a cache table `betting_service.
recompute_leaderboard` writes as a side effect of `settle_market`). That cache has a real
staleness bug: `settle_market` only recomputes it while a market is still transitioning to
SETTLED -- once `bet_market.status == SETTLED`, every later call to `settle_market` for that
market short-circuits at its very first line and never touches the leaderboard again. Any
prediction settled with data that later turns out to have been wrong (e.g. an odds value from
before `MAX_ODDS` existed as a safety cap) leaves a permanently-frozen, arbitrarily-wrong number
in `LeaderboardEntry` with no way to self-heal -- which is exactly how the "Ranking" tab once
showed a user +1,222,036 tokens while their own account page (computed live) showed +124.
Recomputing live every request costs one grouped SQL query and can never go stale.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BetMarket, Prediction, TournamentBalance, User
from app.models.enums import PredictionStatus


@dataclass(frozen=True)
class LeaderboardRow:
    user_id: int
    display_name: str
    # Net profit/loss (payout minus stake) summed across every SETTLED prediction in scope.
    total_points: float
    # Distinct tournaments this user has at least one settled prediction in, within scope.
    tournaments_played: int
    # Play-token wallet -- also reflects tokens tied up in OPEN predictions, not just settled
    # skill, so it's shown alongside total_points, not instead of. Scoped to `tournament_id`'s
    # own TournamentBalance when the leaderboard is per-tournament; summed across every
    # tournament this user has a balance in for the platform-wide "Ranking" tab
    # (`tournament_id=None`), since there's no single global wallet anymore (CNADE 2026 Roadmap
    # Pieza 3).
    balance: float


async def compute_leaderboard(
    session: AsyncSession, *, tournament_id: int | None = None
) -> list[LeaderboardRow]:
    """Every user with at least one SETTLED prediction in scope, ranked by summed net profit,
    ties broken by display_name for a stable order. `tournament_id=None` scopes across every
    tournament (the platform-wide "Ranking" tab); passing one scopes to a single tournament's
    own leaderboard. Empty list if nobody's settled a prediction in scope yet."""
    net_profit = func.sum(Prediction.points_awarded - Prediction.stake_amount)
    stmt = (
        select(
            User.id,
            User.display_name,
            net_profit,
            func.count(func.distinct(BetMarket.tournament_id)),
        )
        .join(Prediction, Prediction.user_id == User.id)
        .join(BetMarket, Prediction.bet_market_id == BetMarket.id)
        .where(Prediction.status == PredictionStatus.SETTLED)
    )
    if tournament_id is not None:
        stmt = stmt.where(BetMarket.tournament_id == tournament_id)
    stmt = stmt.group_by(User.id, User.display_name).order_by(net_profit.desc(), User.display_name)

    rows = (await session.execute(stmt)).all()

    balance_stmt = select(TournamentBalance.user_id, func.sum(TournamentBalance.balance))
    if tournament_id is not None:
        balance_stmt = balance_stmt.where(TournamentBalance.tournament_id == tournament_id)
    balance_stmt = balance_stmt.group_by(TournamentBalance.user_id)
    balance_by_user = dict((await session.execute(balance_stmt)).all())

    return [
        LeaderboardRow(
            user_id=user_id,
            display_name=display_name,
            total_points=float(total_points or 0.0),
            tournaments_played=int(tournaments_played),
            balance=float(balance_by_user.get(user_id, 0.0)),
        )
        for user_id, display_name, total_points, tournaments_played in rows
    ]
