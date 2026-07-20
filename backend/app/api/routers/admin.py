from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas.admin import (
    AdminUserUpdate,
    ManualEliminationResultIn,
    PendingEliminationDebateOut,
    PendingEliminationTeamOut,
    ScrapeLogOut,
)
from app.api.schemas.auth import UserOut
from app.db.session import get_db
from app.models import ScrapeLog, User
from app.services.manual_results_service import (
    ManualResultError,
    apply_manual_advancing_teams,
    apply_manual_champion,
    get_pending_elimination_debates,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/scrape-logs", response_model=list[ScrapeLogOut])
async def list_scrape_logs(
    tournament_id: int | None = None, session: AsyncSession = Depends(get_db)
) -> list[ScrapeLog]:
    stmt = select(ScrapeLog)
    if tournament_id is not None:
        stmt = stmt.where(ScrapeLog.tournament_id == tournament_id)
    stmt = stmt.order_by(ScrapeLog.started_at.desc())
    return list((await session.execute(stmt)).scalars().all())


@router.get("/users", response_model=list[UserOut])
async def list_users(session: AsyncSession = Depends(get_db)) -> list[User]:
    stmt = select(User).order_by(User.id)
    return list((await session.execute(stmt)).scalars().all())


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, payload: AdminUserUpdate, session: AsyncSession = Depends(get_db)
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/pending-elimination-results", response_model=list[PendingEliminationDebateOut])
async def list_pending_elimination_results(
    tournament_id: int | None = None, session: AsyncSession = Depends(get_db)
) -> list[PendingEliminationDebateOut]:
    """Elimination-round debates (including the Grand Final) whose draw is known but whose
    result Tabbycat hasn't published -- surfaced here so an admin can enter it by hand instead
    of editing the database directly. See app.services.manual_results_service."""
    pending = await get_pending_elimination_debates(session, tournament_id)
    return [
        PendingEliminationDebateOut(
            debate_id=item.debate.id,
            tournament_id=item.debate.tournament_id,
            round_id=item.round.id,
            round_name=item.round.name,
            is_final=item.is_final,
            teams=[
                PendingEliminationTeamOut(team_id=dt.team_id, team_name=dt.team.name)
                for dt in item.debate.teams
            ],
        )
        for item in pending
    ]


@router.post("/debates/{debate_id}/manual-result")
async def submit_manual_elimination_result(
    debate_id: int, payload: ManualEliminationResultIn, session: AsyncSession = Depends(get_db)
) -> dict:
    try:
        if payload.champion_team_id is not None:
            await apply_manual_champion(session, debate_id, payload.champion_team_id)
        else:
            assert payload.advancing_team_ids is not None
            await apply_manual_advancing_teams(session, debate_id, payload.advancing_team_ids)
    except ManualResultError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return {"status": "ok"}
