"""Reads the current DebateTeam/SpeakerScore rows and turns them into a ranked standings table.

This is the ONLY place `domain.ranking.compute_standings` gets called from -- Team Points and
Speaker totals are never persisted as their own columns (see the DebateTeam model docstring),
so "what's the current ranking" is always computed fresh from the debate-level rows that are
the actual source of truth. `as_of_round_seq` lets the Break Predictor ask "what did the
standings look like right after round N", not just "right now".
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ranking import DebateTeamRecord, TeamStanding, compute_standings
from app.models import Debate, DebateTeam, Round, Team, TeamBreakCategory
from app.models.enums import RoundStage


async def get_debate_team_records(
    session: AsyncSession,
    tournament_id: int,
    *,
    as_of_round_seq: int | None = None,
    break_category_id: int | None = None,
) -> list[DebateTeamRecord]:
    stmt = (
        select(DebateTeam, Round.seq)
        .join(Debate, DebateTeam.debate_id == Debate.id)
        .join(Round, Debate.round_id == Round.id)
        .where(
            Round.tournament_id == tournament_id,
            Round.stage == RoundStage.PRELIMINARY,
            DebateTeam.rank_in_debate.is_not(None),
        )
    )
    if as_of_round_seq is not None:
        stmt = stmt.where(Round.seq <= as_of_round_seq)
    if break_category_id is not None:
        stmt = (
            stmt.join(Team, DebateTeam.team_id == Team.id)
            .join(TeamBreakCategory, TeamBreakCategory.team_id == Team.id)
            .where(TeamBreakCategory.break_category_id == break_category_id)
        )

    rows = (await session.execute(stmt)).all()
    return [
        DebateTeamRecord(
            team_id=dt.team_id,
            rank_in_debate=dt.rank_in_debate,
            speaker_points=dt.speaker_points_total,
        )
        for dt, _round_seq in rows
    ]


async def get_standings(
    session: AsyncSession,
    tournament_id: int,
    *,
    as_of_round_seq: int | None = None,
    break_category_id: int | None = None,
) -> list[TeamStanding]:
    records = await get_debate_team_records(
        session,
        tournament_id,
        as_of_round_seq=as_of_round_seq,
        break_category_id=break_category_id,
    )
    return compute_standings(records)


async def get_latest_completed_round_seq(session: AsyncSession, tournament_id: int) -> int | None:
    stmt = (
        select(Round.seq)
        .where(Round.tournament_id == tournament_id, Round.stage == RoundStage.PRELIMINARY)
        .join(Debate, Debate.round_id == Round.id)
        .join(DebateTeam, DebateTeam.debate_id == Debate.id)
        .where(DebateTeam.rank_in_debate.is_not(None))
        .order_by(Round.seq.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_total_preliminary_rounds(session: AsyncSession, tournament_id: int) -> int:
    stmt = select(Round.seq).where(
        Round.tournament_id == tournament_id, Round.stage == RoundStage.PRELIMINARY
    )
    seqs = (await session.execute(stmt)).scalars().all()
    return len(seqs)
