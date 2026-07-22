from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas.rounds import RoundOut
from app.api.schemas.tournaments import (
    ScrapeQueuedResponse,
    TournamentCreate,
    TournamentOut,
    TournamentUpdate,
)
from app.db.session import get_db
from app.domain.tab_url import parse_tab_url
from app.models import BetMarket, Team, Tournament, User
from app.models.enums import BetMarketStatus
from app.services.tournament_service import create_tournament, get_current_round
from app.tasks.scrape_tasks import scrape_tournament_async

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


async def _get_tournament_or_404(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await session.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


def _parse_tab_url_or_422(tab_url: str) -> tuple[str, str]:
    try:
        return parse_tab_url(tab_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


async def _to_tournament_out(session: AsyncSession, tournament: Tournament) -> TournamentOut:
    out = TournamentOut.model_validate(tournament)
    current_round = await get_current_round(session, tournament.id)
    out.current_round = RoundOut.model_validate(current_round) if current_round else None
    out.teams_count = int(
        (
            await session.execute(
                select(func.count(Team.id)).where(Team.tournament_id == tournament.id)
            )
        ).scalar_one()
    )
    out.open_markets_count = int(
        (
            await session.execute(
                select(func.count(BetMarket.id)).where(
                    BetMarket.tournament_id == tournament.id,
                    BetMarket.status == BetMarketStatus.OPEN,
                )
            )
        ).scalar_one()
    )
    return out


@router.get("", response_model=list[TournamentOut])
async def list_tournaments(session: AsyncSession = Depends(get_db)) -> list[TournamentOut]:
    tournaments = (
        (await session.execute(select(Tournament).order_by(Tournament.id))).scalars().all()
    )
    return [await _to_tournament_out(session, t) for t in tournaments]


@router.get("/{tournament_id}", response_model=TournamentOut)
async def get_tournament(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> TournamentOut:
    tournament = await _get_tournament_or_404(session, tournament_id)
    return await _to_tournament_out(session, tournament)


@router.post("", response_model=TournamentOut, status_code=status.HTTP_201_CREATED)
async def create_tournament_endpoint(
    payload: TournamentCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> Tournament:
    source_base_url, source_slug = _parse_tab_url_or_422(payload.tab_url)
    try:
        tournament = await create_tournament(
            session,
            name=payload.name,
            source_base_url=source_base_url,
            source_slug=source_slug,
            timezone=payload.timezone,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ya existe un torneo registrado para {source_base_url}/{source_slug} -- "
                "no hace falta agregarlo de nuevo."
            ),
        ) from exc
    await session.refresh(tournament)
    # Start tracking it immediately instead of leaving an empty shell until the admin remembers
    # to click "Forzar scraping" separately.
    background_tasks.add_task(scrape_tournament_async, tournament.id)
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
    tab_url = updates.pop("tab_url", None)
    if tab_url is not None:
        source_base_url, source_slug = _parse_tab_url_or_422(tab_url)
        updates["source_base_url"] = source_base_url
        updates["source_slug"] = source_slug
    for field, value in updates.items():
        setattr(tournament, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe otro torneo registrado con esa URL.",
        ) from exc
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
