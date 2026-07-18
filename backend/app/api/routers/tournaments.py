from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas.tournaments import (
    ScrapeQueuedResponse,
    TournamentCreate,
    TournamentOut,
    TournamentUpdate,
)
from app.db.session import get_db
from app.models import Tournament, User
from app.services.tournament_service import create_tournament
from app.tasks.scrape_tasks import scrape_tournament_async

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


async def _get_tournament_or_404(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await session.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


@router.get("", response_model=list[TournamentOut])
async def list_tournaments(session: AsyncSession = Depends(get_db)) -> list[Tournament]:
    return list((await session.execute(select(Tournament).order_by(Tournament.id))).scalars().all())


@router.get("/{tournament_id}", response_model=TournamentOut)
async def get_tournament(tournament_id: int, session: AsyncSession = Depends(get_db)) -> Tournament:
    return await _get_tournament_or_404(session, tournament_id)


@router.post("", response_model=TournamentOut, status_code=status.HTTP_201_CREATED)
async def create_tournament_endpoint(
    payload: TournamentCreate,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> Tournament:
    tournament = await create_tournament(
        session,
        name=payload.name,
        source_base_url=payload.source_base_url,
        source_slug=payload.source_slug,
        timezone=payload.timezone,
    )
    await session.commit()
    await session.refresh(tournament)
    return tournament


@router.patch("/{tournament_id}", response_model=TournamentOut)
async def update_tournament(
    tournament_id: int,
    payload: TournamentUpdate,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> Tournament:
    tournament = await _get_tournament_or_404(session, tournament_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(tournament, field, value)
    await session.commit()
    await session.refresh(tournament)
    return tournament


@router.post("/{tournament_id}/scrape", response_model=ScrapeQueuedResponse)
async def scrape_tournament_endpoint(
    tournament_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ScrapeQueuedResponse:
    """Triggers a scrape for this tournament.

    This dev/friends-scale deployment has no live Redis/Celery worker guaranteed to be running,
    so rather than depending on `scrape_tournament.delay(...)` (which would silently do nothing
    -- or hang -- without a broker), this calls `scrape_tournament_async` directly via FastAPI's
    `BackgroundTasks`. That's the same Celery-independent async function the real
    `scrape_tournament` Celery task wraps, so behaviour is identical; only the execution
    mechanism differs. The periodic Celery beat schedule in `app/tasks/celery_app.py` is
    untouched and still drives the recurring background scrape in a real deployment.
    """
    await _get_tournament_or_404(session, tournament_id)
    background_tasks.add_task(scrape_tournament_async, tournament_id)
    return ScrapeQueuedResponse()
