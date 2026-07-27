import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.leaderboard import (
    GlobalLeaderboardEntryOut,
    LeaderboardEntryOut,
    LeaderboardUserOut,
)
from app.db.session import get_db
from app.services.leaderboard_service import compute_leaderboard

router = APIRouter(tags=["leaderboard"])


@router.get("/tournaments/{tournament_id}/leaderboard", response_model=list[LeaderboardEntryOut])
async def get_leaderboard(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[LeaderboardEntryOut]:
    rows = await compute_leaderboard(session, tournament_id=tournament_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    return [
        LeaderboardEntryOut(
            user=LeaderboardUserOut(id=row.user_id, display_name=row.display_name),
            total_points=row.total_points,
            rank=i + 1,
            computed_at=now,
        )
        for i, row in enumerate(rows)
    ]


@router.get("/leaderboard/global", response_model=list[GlobalLeaderboardEntryOut])
async def get_global_leaderboard(
    session: AsyncSession = Depends(get_db),
) -> list[GlobalLeaderboardEntryOut]:
    """Ranking de apostadores: net profit summed across every tournament, for the platform-wide
    "Ranking" tab -- distinct from the per-tournament leaderboard embedded in a tournament's own
    page. See app.services.leaderboard_service."""
    rows = await compute_leaderboard(session)
    return [
        GlobalLeaderboardEntryOut(
            user=LeaderboardUserOut(id=row.user_id, display_name=row.display_name),
            total_points=row.total_points,
            tournaments_played=row.tournaments_played,
            balance=row.balance,
            rank=i + 1,
        )
        for i, row in enumerate(rows)
    ]
