from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.participants import InstitutionOut, SpeakerOut, TeamOut
from app.api.schemas.rounds import (
    DebateAdjudicatorOut,
    DebateDetailOut,
    DebateSpeakerScoreOut,
    DebateSummaryOut,
    DebateTeamDetailOut,
    DebateTeamSummaryOut,
    RoomOut,
    RoundOut,
)
from app.db.session import get_db
from app.models import Debate, DebateAdjudicator, DebateTeam, Round, Speaker, SpeakerScore, Team

router = APIRouter(prefix="/tournaments/{tournament_id}", tags=["rounds"])


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


async def _get_round_or_404(session: AsyncSession, tournament_id: int, round_id: int) -> Round:
    round_ = (
        await session.execute(
            select(Round).where(Round.tournament_id == tournament_id, Round.id == round_id)
        )
    ).scalar_one_or_none()
    if round_ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Round not found")
    return round_


@router.get("/rounds", response_model=list[RoundOut])
async def list_rounds(tournament_id: int, session: AsyncSession = Depends(get_db)) -> list[Round]:
    stmt = select(Round).where(Round.tournament_id == tournament_id).order_by(Round.seq)
    return list((await session.execute(stmt)).scalars().all())


@router.get("/rounds/{round_id}/debates", response_model=list[DebateSummaryOut])
async def list_round_debates(
    tournament_id: int, round_id: int, session: AsyncSession = Depends(get_db)
) -> list[DebateSummaryOut]:
    await _get_round_or_404(session, tournament_id, round_id)

    stmt = (
        select(Debate)
        .where(Debate.tournament_id == tournament_id, Debate.round_id == round_id)
        .options(
            selectinload(Debate.room),
            selectinload(Debate.teams).selectinload(DebateTeam.team).selectinload(Team.institution),
            selectinload(Debate.teams)
            .selectinload(DebateTeam.team)
            .selectinload(Team.speakers)
            .selectinload(Speaker.categories),
        )
        .order_by(Debate.external_id)
    )
    debates = (await session.execute(stmt)).scalars().all()

    return [
        DebateSummaryOut(
            id=debate.id,
            room=RoomOut(name=debate.room.name) if debate.room else None,
            status=debate.status,
            teams=[
                DebateTeamSummaryOut(
                    team=_team_schema(dt.team),
                    position=dt.position,
                    rank_in_debate=dt.rank_in_debate,
                    team_points=dt.team_points,
                )
                for dt in debate.teams
            ],
        )
        for debate in debates
    ]


@router.get("/debates/{debate_id}", response_model=DebateDetailOut)
async def get_debate(
    tournament_id: int, debate_id: int, session: AsyncSession = Depends(get_db)
) -> DebateDetailOut:
    stmt = (
        select(Debate)
        .where(Debate.tournament_id == tournament_id, Debate.id == debate_id)
        .options(
            selectinload(Debate.round),
            selectinload(Debate.room),
            selectinload(Debate.result),
            selectinload(Debate.adjudicators).selectinload(DebateAdjudicator.adjudicator),
            selectinload(Debate.teams).selectinload(DebateTeam.team).selectinload(Team.institution),
            selectinload(Debate.teams).selectinload(DebateTeam.team).selectinload(Team.speakers),
            selectinload(Debate.teams)
            .selectinload(DebateTeam.speaker_scores)
            .selectinload(SpeakerScore.speaker)
            .selectinload(Speaker.categories),
        )
    )
    debate = (await session.execute(stmt)).scalar_one_or_none()
    if debate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found")

    return DebateDetailOut(
        id=debate.id,
        round=RoundOut.model_validate(debate.round),
        room=RoomOut(name=debate.room.name) if debate.room else None,
        status=debate.status,
        motion_text=debate.result.motion_text if debate.result else None,
        ballot_source_url=debate.result.ballot_source_url if debate.result else None,
        teams=[
            DebateTeamDetailOut(
                team=_team_schema(dt.team),
                position=dt.position,
                rank_in_debate=dt.rank_in_debate,
                team_points=dt.team_points,
                speaker_points_total=dt.speaker_points_total,
                speakers=[
                    DebateSpeakerScoreOut(
                        speaker=_speaker_schema(score.speaker),
                        role=score.role,
                        score=score.score,
                        is_iron=score.is_iron,
                    )
                    for score in dt.speaker_scores
                ],
            )
            for dt in debate.teams
        ],
        adjudicators=[
            DebateAdjudicatorOut(
                adjudicator_id=da.adjudicator_id,
                name=da.adjudicator.name,
                role=da.role,
            )
            for da in debate.adjudicators
        ],
    )
