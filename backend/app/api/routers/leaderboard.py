from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.leaderboard import (
    GlobalLeaderboardEntryOut,
    LeaderboardEntryOut,
    LeaderboardUserOut,
)
from app.db.session import get_db
from app.models import LeaderboardEntry
from app.services.global_leaderboard_service import compute_global_leaderboard

router = APIRouter(tags=["leaderboard"])


@router.get("/tournaments/{tournament_id}/leaderboard", response_model=list[LeaderboardEntryOut])
async def get_leaderboard(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[LeaderboardEntryOut]:
    stmt = (
        select(LeaderboardEntry)
        .where(LeaderboardEntry.tournament_id == tournament_id)
        .options(selectinload(LeaderboardEntry.user))
        .order_by(LeaderboardEntry.rank)
    )
    entries = (await session.execute(stmt)).scalars().all()
    return [
        LeaderboardEntryOut(
            user=LeaderboardUserOut(id=entry.user.id, display_name=entry.user.display_name),
            total_points=entry.total_points,
            rank=entry.rank,
            computed_at=entry.computed_at,
        )
        for entry in entries
    ]


@router.get("/leaderboard/global", response_model=list[GlobalLeaderboardEntryOut])
async def get_global_leaderboard(
    session: AsyncSession = Depends(get_db),
) -> list[GlobalLeaderboardEntryOut]:
    """Ranking de apostadores: net profit summed across every tournament, for the platform-wide
    "Ranking" tab -- distinct from the per-tournament leaderboard embedded in a tournament's own
    page. See app.services.global_leaderboard_service."""
    entries = await compute_global_leaderboard(session)
    return [
        GlobalLeaderboardEntryOut(
            user=LeaderboardUserOut(id=e.user_id, display_name=e.display_name),
            total_points=e.total_points,
            tournaments_played=e.tournaments_played,
            balance=e.balance,
            rank=i + 1,
        )
        for i, e in enumerate(entries)
    ]
