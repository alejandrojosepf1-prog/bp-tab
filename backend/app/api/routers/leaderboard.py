from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.leaderboard import LeaderboardEntryOut, LeaderboardUserOut
from app.db.session import get_db
from app.models import LeaderboardEntry

router = APIRouter(prefix="/tournaments/{tournament_id}", tags=["leaderboard"])


@router.get("/leaderboard", response_model=list[LeaderboardEntryOut])
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
