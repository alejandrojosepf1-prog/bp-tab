from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.breaks import BreakAssessmentOut, BreakCategoryOut, BreakEntryOut
from app.api.schemas.participants import InstitutionOut, SpeakerOut, TeamOut
from app.db.session import get_db
from app.models import Break, BreakCategory, Speaker, Team
from app.services.break_service import recompute_break_predictions

router = APIRouter(prefix="/tournaments/{tournament_id}", tags=["breaks"])


def _speaker_schema(speaker: Speaker) -> SpeakerOut:
    return SpeakerOut(
        id=speaker.id,
        name=speaker.name,
        team_id=speaker.team_id,
        categories=[category.name for category in speaker.categories],
    )


def _team_schema(team: Team) -> TeamOut:
    return TeamOut(
        id=team.id,
        external_id=team.external_id,
        name=team.name,
        emoji=team.emoji,
        institution=InstitutionOut.model_validate(team.institution) if team.institution else None,
        speakers=[_speaker_schema(s) for s in team.speakers],
    )


async def _teams_by_id(session: AsyncSession, team_ids: list[int]) -> dict[int, Team]:
    if not team_ids:
        return {}
    stmt = (
        select(Team)
        .where(Team.id.in_(team_ids))
        .options(
            selectinload(Team.institution),
            selectinload(Team.speakers).selectinload(Speaker.categories),
        )
    )
    return {t.id: t for t in (await session.execute(stmt)).scalars().all()}


@router.get("/break-categories", response_model=list[BreakCategoryOut])
async def list_break_categories(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[BreakCategory]:
    stmt = (
        select(BreakCategory)
        .where(BreakCategory.tournament_id == tournament_id)
        .order_by(BreakCategory.name)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/break-categories/{category_id}/predictions", response_model=list[BreakAssessmentOut])
async def get_break_predictions(
    tournament_id: int, category_id: int, session: AsyncSession = Depends(get_db)
) -> list[BreakAssessmentOut]:
    """Computed live from current standings on every call (see `break_service.
    recompute_break_predictions`) rather than read back from the `break_predictions` table --
    there's no guarantee a Celery worker has run recently in this dev/friends-scale deployment,
    and the computation itself is cheap (a handful of teams, a few thousand simulated draws).
    The service still persists a snapshot as a side effect via `upsert_by_natural_key`, but this
    request's session is never committed here, so nothing is written unless some other code path
    (e.g. the scrape task) later commits its own recompute.
    """
    report = await recompute_break_predictions(session, tournament_id, category_id)
    if not report:
        return []

    teams_by_id = await _teams_by_id(session, [a.team_id for a in report])
    return [
        BreakAssessmentOut(
            team=_team_schema(teams_by_id[a.team_id]),
            status=a.status,
            probability=a.probability,
            projected_rank=a.projected_rank,
            points_needed_for_safety=a.points_needed_for_safety,
        )
        for a in report
        if a.team_id in teams_by_id
    ]


@router.get("/break-categories/{category_id}/break", response_model=list[BreakEntryOut])
async def get_official_break(
    tournament_id: int, category_id: int, session: AsyncSession = Depends(get_db)
) -> list[BreakEntryOut]:
    stmt = (
        select(Break)
        .where(Break.tournament_id == tournament_id, Break.break_category_id == category_id)
        .order_by(Break.rank)
    )
    entries = (await session.execute(stmt)).scalars().all()
    if not entries:
        return []

    teams_by_id = await _teams_by_id(session, [e.team_id for e in entries])
    return [
        BreakEntryOut(team=_team_schema(teams_by_id[e.team_id]), rank=e.rank)
        for e in entries
        if e.team_id in teams_by_id
    ]
