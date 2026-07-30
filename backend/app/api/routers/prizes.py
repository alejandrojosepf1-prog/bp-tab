from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_admin
from app.api.schemas.prizes import (
    ManualAwardQueue,
    PrizeEntryOut,
    PrizeEventCreate,
    PrizeEventDetailOut,
    PrizeEventOut,
    RaffleEntryIn,
)
from app.db.session import get_db
from app.models import PrizeEntry, PrizeEvent, Tournament, User
from app.services.prize_service import (
    InsufficientBalanceError,
    PrizeEventError,
    enter_raffle,
    queue_manual_award,
    resolve_prize_event,
)

router = APIRouter(tags=["prizes"])


async def _get_event_or_404(session: AsyncSession, event_id: int) -> PrizeEvent:
    event = await session.get(PrizeEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prize event not found")
    return event


async def _to_event_out(session: AsyncSession, event: PrizeEvent) -> PrizeEventOut:
    """entry_count/total_tickets are computed, not columns -- same reasoning as BetMarket's
    pool_total/bettors_count in app.api.routers.betting: cheap aggregate queries beat a
    denormalized counter that could drift."""
    row = (
        await session.execute(
            select(func.count(PrizeEntry.id), func.coalesce(func.sum(PrizeEntry.tickets), 0)).where(
                PrizeEntry.prize_event_id == event.id
            )
        )
    ).one()
    out = PrizeEventOut.model_validate(event)
    out.entry_count = int(row[0])
    out.total_tickets = int(row[1])
    return out


@router.get("/tournaments/{tournament_id}/prize-events", response_model=list[PrizeEventOut])
async def list_prize_events(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[PrizeEventOut]:
    stmt = (
        select(PrizeEvent)
        .where(PrizeEvent.tournament_id == tournament_id)
        .order_by(PrizeEvent.created_at.desc())
    )
    events = (await session.execute(stmt)).scalars().all()
    return [await _to_event_out(session, e) for e in events]


@router.post(
    "/tournaments/{tournament_id}/prize-events",
    response_model=PrizeEventOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_prize_event(
    tournament_id: int,
    payload: PrizeEventCreate,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> PrizeEventOut:
    tournament = await session.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    event = PrizeEvent(
        tournament_id=tournament_id,
        type=payload.type,
        title=payload.title,
        description=payload.description,
        config=payload.config,
        closes_at=payload.closes_at,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return await _to_event_out(session, event)


@router.get("/prize-events/{event_id}", response_model=PrizeEventDetailOut)
async def get_prize_event(
    event_id: int, session: AsyncSession = Depends(get_db)
) -> PrizeEventDetailOut:
    stmt = (
        select(PrizeEvent)
        .where(PrizeEvent.id == event_id)
        .options(selectinload(PrizeEvent.entries).selectinload(PrizeEntry.user))
    )
    event = (await session.execute(stmt)).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prize event not found")
    base = await _to_event_out(session, event)
    return PrizeEventDetailOut(
        **base.model_dump(),
        entries=[PrizeEntryOut.model_validate(e) for e in event.entries],
    )


@router.post(
    "/prize-events/{event_id}/manual-awards",
    response_model=PrizeEntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def queue_manual_award_route(
    event_id: int,
    payload: ManualAwardQueue,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> PrizeEntryOut:
    event = await _get_event_or_404(session, event_id)
    target_user = await session.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        entry = await queue_manual_award(session, event, payload.user_id, payload.amount)
    except PrizeEventError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(entry, attribute_names=["user"])
    return PrizeEntryOut.model_validate(entry)


@router.post(
    "/prize-events/{event_id}/enter",
    response_model=PrizeEntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def enter_raffle_route(
    event_id: int,
    payload: RaffleEntryIn,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PrizeEntryOut:
    event = await _get_event_or_404(session, event_id)
    try:
        entry = await enter_raffle(session, event, current_user, payload.tickets)
    except PrizeEventError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(entry, attribute_names=["user"])
    return PrizeEntryOut.model_validate(entry)


@router.post("/prize-events/{event_id}/resolve", response_model=PrizeEventDetailOut)
async def resolve_prize_event_route(
    event_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> PrizeEventDetailOut:
    event = await _get_event_or_404(session, event_id)
    try:
        await resolve_prize_event(session, event)
    except PrizeEventError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return await get_prize_event(event_id, session)
