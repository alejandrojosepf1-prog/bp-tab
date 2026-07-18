from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.participants import AdjudicatorOut, InstitutionOut, SpeakerOut, TeamOut
from app.db.session import get_db
from app.models import Adjudicator, AdjudicatorBreak, Institution, Speaker, Team

router = APIRouter(prefix="/tournaments/{tournament_id}", tags=["participants"])


def _speaker_to_schema(speaker: Speaker) -> SpeakerOut:
    return SpeakerOut(
        id=speaker.id,
        name=speaker.name,
        team_id=speaker.team_id,
        categories=[category.name for category in speaker.categories],
    )


def _team_to_schema(team: Team) -> TeamOut:
    return TeamOut(
        id=team.id,
        external_id=team.external_id,
        name=team.name,
        emoji=team.emoji,
        institution=InstitutionOut.model_validate(team.institution) if team.institution else None,
        speakers=[_speaker_to_schema(s) for s in team.speakers],
    )


@router.get("/institutions", response_model=list[InstitutionOut])
async def list_institutions(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[Institution]:
    stmt = (
        select(Institution)
        .where(Institution.tournament_id == tournament_id)
        .order_by(Institution.name)
    )
    return list((await session.execute(stmt)).scalars().all())


def _teams_stmt(tournament_id: int) -> Select:
    return (
        select(Team)
        .where(Team.tournament_id == tournament_id)
        .options(
            selectinload(Team.institution),
            selectinload(Team.speakers).selectinload(Speaker.categories),
        )
        .order_by(Team.name)
    )


@router.get("/teams", response_model=list[TeamOut])
async def list_teams(tournament_id: int, session: AsyncSession = Depends(get_db)) -> list[TeamOut]:
    stmt = _teams_stmt(tournament_id)
    teams = (await session.execute(stmt)).scalars().all()
    return [_team_to_schema(t) for t in teams]


@router.get("/teams/{team_id}", response_model=TeamOut)
async def get_team(
    tournament_id: int, team_id: int, session: AsyncSession = Depends(get_db)
) -> TeamOut:
    stmt = (
        select(Team)
        .where(Team.tournament_id == tournament_id, Team.id == team_id)
        .options(
            selectinload(Team.institution),
            selectinload(Team.speakers).selectinload(Speaker.categories),
        )
    )
    team = (await session.execute(stmt)).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return _team_to_schema(team)


@router.get("/speakers", response_model=list[SpeakerOut])
async def list_speakers(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[SpeakerOut]:
    stmt = (
        select(Speaker)
        .where(Speaker.tournament_id == tournament_id)
        .options(selectinload(Speaker.categories))
        .order_by(Speaker.name)
    )
    speakers = (await session.execute(stmt)).scalars().all()
    return [_speaker_to_schema(s) for s in speakers]


@router.get("/adjudicators", response_model=list[AdjudicatorOut])
async def list_adjudicators(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[AdjudicatorOut]:
    stmt = (
        select(Adjudicator)
        .where(Adjudicator.tournament_id == tournament_id)
        .options(selectinload(Adjudicator.institution))
        .order_by(Adjudicator.name)
    )
    adjudicators = (await session.execute(stmt)).scalars().all()

    broke_ids = set(
        (
            await session.execute(
                select(AdjudicatorBreak.adjudicator_id).where(
                    AdjudicatorBreak.tournament_id == tournament_id
                )
            )
        )
        .scalars()
        .all()
    )

    return [
        AdjudicatorOut(
            id=adj.id,
            external_id=adj.external_id,
            name=adj.name,
            institution=InstitutionOut.model_validate(adj.institution) if adj.institution else None,
            is_independent=adj.is_independent,
            broke=adj.id in broke_ids,
        )
        for adj in adjudicators
    ]
