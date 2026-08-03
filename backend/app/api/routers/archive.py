"""Public, read-only endpoints for the circuit archive (CNADE 2026 Roadmap Pieza 2). No auth
anywhere in this file, same pattern as app.api.routers.participants -- this is the whole point,
a public "what has this institution/motion history looked like across years" view, distinct from
the per-tournament participant lists those other routers expose."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.archive import (
    CircuitInstitutionDetailOut,
    CircuitInstitutionOut,
    InstitutionTournamentAppearanceOut,
    MotionEntryOut,
)
from app.db.session import get_db
from app.models import CircuitInstitution, Institution, Round, Tournament
from app.models.enums import MotionCategory, TournamentStatus

router = APIRouter(tags=["archive"])


@router.get("/circuit/institutions", response_model=list[CircuitInstitutionOut])
async def list_circuit_institutions(
    session: AsyncSession = Depends(get_db),
) -> list[CircuitInstitution]:
    stmt = select(CircuitInstitution).order_by(CircuitInstitution.name)
    return list((await session.execute(stmt)).scalars().all())


@router.get("/circuit/institutions/{slug}", response_model=CircuitInstitutionDetailOut)
async def get_circuit_institution(
    slug: str, session: AsyncSession = Depends(get_db)
) -> CircuitInstitutionDetailOut:
    circuit_institution = (
        await session.execute(select(CircuitInstitution).where(CircuitInstitution.slug == slug))
    ).scalar_one_or_none()
    if circuit_institution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")

    per_tournament_rows = (
        (
            await session.execute(
                select(Institution)
                .where(Institution.circuit_institution_id == circuit_institution.id)
                .options(selectinload(Institution.teams))
            )
        )
        .scalars()
        .all()
    )

    tournament_ids = {row.tournament_id for row in per_tournament_rows}
    tournaments_by_id = {
        t.id: t
        for t in (
            await session.execute(select(Tournament).where(Tournament.id.in_(tournament_ids)))
        )
        .scalars()
        .all()
    }

    appearances = []
    for row in per_tournament_rows:
        tournament = tournaments_by_id.get(row.tournament_id)
        if tournament is None:
            continue
        appearances.append(
            InstitutionTournamentAppearanceOut(
                tournament_name=tournament.name,
                tournament_slug=tournament.slug,
                tournament_year=tournament.year,
                team_names=[team.name for team in row.teams],
                was_champion=any(team.id == tournament.champion_team_id for team in row.teams),
            )
        )
    appearances.sort(key=lambda a: a.tournament_year or 0, reverse=True)

    return CircuitInstitutionDetailOut(
        id=circuit_institution.id,
        name=circuit_institution.name,
        slug=circuit_institution.slug,
        region=circuit_institution.region,
        appearances=appearances,
    )


@router.get("/motions", response_model=list[MotionEntryOut])
async def list_motions(
    category: MotionCategory | None = Query(default=None),
    year: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[MotionEntryOut]:
    """Browsable by category/year -- only for COMPLETED tournaments. `Round.motion_category` is
    deliberately withheld from every other public schema pre-settlement (it's the ground truth
    for the MOTION_TYPE bet market); once a tournament is archived that concern no longer
    applies, but the gate has to be explicit here since nothing upstream enforces it."""
    stmt = (
        select(Round, Tournament)
        .join(Tournament, Tournament.id == Round.tournament_id)
        .where(Tournament.status == TournamentStatus.COMPLETED, Round.motion_text.is_not(None))
    )
    if category is not None:
        stmt = stmt.where(Round.motion_category == category)
    if year is not None:
        stmt = stmt.where(Tournament.year == year)

    rows = (await session.execute(stmt)).all()
    entries = [
        MotionEntryOut(
            tournament_name=tournament.name,
            tournament_slug=tournament.slug,
            tournament_year=tournament.year,
            round_name=round_.name,
            motion_text=round_.motion_text,
            motion_category=round_.motion_category,
        )
        for round_, tournament in rows
    ]
    entries.sort(
        key=lambda e: (e.tournament_year or 0, e.tournament_name, e.round_name), reverse=True
    )
    return entries
