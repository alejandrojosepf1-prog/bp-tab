from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas.access_passes import AccessPassOut, AccessPassRequestIn
from app.db.session import get_db
from app.models import AccessPass, Tournament, User
from app.models.enums import AccessPassStatus
from app.services.access_pass_service import (
    AccessPassError,
    approve_access_pass,
    reject_access_pass,
    submit_access_pass_request,
)

router = APIRouter(tags=["access-passes"])


async def _get_pass_or_404(session: AsyncSession, access_pass_id: int) -> AccessPass:
    access_pass = await session.get(AccessPass, access_pass_id)
    if access_pass is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access pass not found")
    return access_pass


@router.post(
    "/tournaments/{tournament_id}/access-passes",
    response_model=AccessPassOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_access_pass_request(
    tournament_id: int,
    payload: AccessPassRequestIn,
    session: AsyncSession = Depends(get_db),
) -> AccessPass:
    """Public, no login required -- this is the whole point of a pass request."""
    tournament = await session.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    access_pass = await submit_access_pass_request(
        session,
        tournament_id,
        email=payload.email.strip().lower(),
        phone=payload.phone.strip(),
        full_name=payload.full_name.strip(),
    )
    await session.commit()
    await session.refresh(access_pass)
    return access_pass


@router.get("/admin/access-passes", response_model=list[AccessPassOut])
async def list_access_passes(
    tournament_id: int,
    status_filter: AccessPassStatus | None = None,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[AccessPass]:
    stmt = select(AccessPass).where(AccessPass.tournament_id == tournament_id)
    if status_filter is not None:
        stmt = stmt.where(AccessPass.status == status_filter)
    stmt = stmt.order_by(AccessPass.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


@router.post("/admin/access-passes/{access_pass_id}/approve", response_model=AccessPassOut)
async def approve_access_pass_route(
    access_pass_id: int,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AccessPass:
    access_pass = await _get_pass_or_404(session, access_pass_id)
    try:
        await approve_access_pass(session, access_pass, admin)
    except AccessPassError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(access_pass)
    return access_pass


@router.post("/admin/access-passes/{access_pass_id}/reject", response_model=AccessPassOut)
async def reject_access_pass_route(
    access_pass_id: int,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AccessPass:
    access_pass = await _get_pass_or_404(session, access_pass_id)
    try:
        await reject_access_pass(session, access_pass, admin)
    except AccessPassError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(access_pass)
    return access_pass
