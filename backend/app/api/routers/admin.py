from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas.admin import AdminUserUpdate, ScrapeLogOut
from app.api.schemas.auth import UserOut
from app.db.session import get_db
from app.models import ScrapeLog, User

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
