from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.participants import InstitutionOut, SpeakerOut, TeamOut
from app.api.schemas.standings import TeamStandingOut
from app.db.session import get_db
from app.models import Speaker, Team
from app.services.ranking_service import get_standings

router = APIRouter(prefix="/tournaments/{tournament_id}", tags=["standings"])


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


@router.get("/standings", response_model=list[TeamStandingOut])
async def get_tournament_standings(
    tournament_id: int,
    break_category_id: int | None = None,
    as_of_round_seq: int | None = None,
    session: AsyncSession = Depends(get_db),
) -> list[TeamStandingOut]:
    standings = await get_standings(
        session,
        tournament_id,
        as_of_round_seq=as_of_round_seq,
        break_category_id=break_category_id,
    )
    if not standings:
        return []

    team_ids = [s.team_id for s in standings]
    stmt = (
        select(Team)
        .where(Team.id.in_(team_ids))
        .options(
            selectinload(Team.institution),
            selectinload(Team.speakers).selectinload(Speaker.categories),
        )
    )
    teams_by_id = {t.id: t for t in (await session.execute(stmt)).scalars().all()}

    return [
        TeamStandingOut(
            team=_team_schema(teams_by_id[s.team_id]),
            rank=s.rank,
            team_points=s.team_points,
            total_speaker_points=s.total_speaker_points,
            firsts=s.firsts,
            seconds=s.seconds,
            thirds=s.thirds,
            fourths=s.fourths,
            debates_played=s.debates_played,
        )
        for s in standings
        if s.team_id in teams_by_id
    ]
