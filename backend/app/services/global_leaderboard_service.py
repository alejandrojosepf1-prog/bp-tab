"""Cross-tournament bettor ranking.

Each `LeaderboardEntry` row is one user's net profit/loss (payout minus stake, across every
SETTLED prediction) within a SINGLE tournament -- see `betting_service.recompute_leaderboard`.
This module sums those per-tournament figures per user to answer "who's the best predictor
across every tournament they've played," a different question from either the per-tournament
leaderboard (skill in ONE tournament) or `User.balance` (current wallet, which also reflects
stakes still tied up in OPEN predictions, not just settled skill).

A derived view like `game_economy_service`, not a new table: nothing here is written back.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeaderboardEntry, User


@dataclass(frozen=True)
class GlobalLeaderboardEntry:
    user_id: int
    display_name: str
    total_points: float
    tournaments_played: int
    balance: float


async def compute_global_leaderboard(session: AsyncSession) -> list[GlobalLeaderboardEntry]:
    """Every user with at least one per-tournament leaderboard entry (i.e. at least one settled
    prediction somewhere), ranked by summed net profit across all of them, ties broken by
    display_name for a stable order. Empty list if nobody has settled a prediction yet."""
    stmt = (
        select(
            User.id,
            User.display_name,
            User.balance,
            func.sum(LeaderboardEntry.total_points),
            func.count(LeaderboardEntry.tournament_id),
        )
        .join(LeaderboardEntry, LeaderboardEntry.user_id == User.id)
        .group_by(User.id, User.display_name, User.balance)
        .order_by(func.sum(LeaderboardEntry.total_points).desc(), User.display_name)
    )
    rows = (await session.execute(stmt)).all()
    return [
        GlobalLeaderboardEntry(
            user_id=user_id,
            display_name=display_name,
            total_points=float(total_points or 0.0),
            tournaments_played=int(tournaments_played),
            balance=float(balance),
        )
        for user_id, display_name, balance, total_points, tournaments_played in rows
    ]
