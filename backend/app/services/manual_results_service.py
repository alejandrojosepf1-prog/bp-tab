"""Manual entry for elimination-round results that Tabbycat's scrape never fills in.

Many tournaments stop entering ballots into Tabbycat once a debate no longer affects the
tab (team points/speaker points aren't published past the break) -- this is especially common
for the Grand Final, which is often never confirmed in Tabbycat at all even though everyone in
the room knows who won. Since BetType.CHAMPION and elimination-round outcomes both read
DebateTeam.rank_in_debate / .advanced and Tournament.champion_team_id, an admin can fill those
same fields by hand here. A later scrape that DOES find an official ballot for the same debate
goes through app.services.ingestion's upsert path and overwrites whatever was entered manually
here -- Tabbycat is always the source of truth once it catches up.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Debate, DebateTeam, Round, Tournament
from app.models.enums import DebateStatus, RoundStage, RoundStatus


class ManualResultError(Exception):
    """Raised when a manual result payload doesn't match the debate it targets."""


@dataclass
class PendingEliminationDebate:
    debate: Debate
    round: Round
    is_final: bool


async def _max_elimination_seq(session: AsyncSession, tournament_id: int) -> int | None:
    stmt = select(Round.seq).where(
        Round.tournament_id == tournament_id, Round.stage == RoundStage.ELIMINATION
    )
    seqs = (await session.execute(stmt)).scalars().all()
    return max(seqs) if seqs else None


async def get_pending_elimination_debates(
    session: AsyncSession, tournament_id: int | None = None
) -> list[PendingEliminationDebate]:
    """Elimination-round debates whose draw is known but whose outcome isn't yet: the Grand
    Final missing its champion, or a quarter/semi-final missing which teams advanced."""
    stmt = (
        select(Debate)
        .join(Round, Debate.round_id == Round.id)
        .where(
            Round.stage == RoundStage.ELIMINATION,
            Round.status.in_([RoundStatus.RELEASED, RoundStatus.COMPLETED]),
        )
        .options(
            selectinload(Debate.round),
            selectinload(Debate.teams).selectinload(DebateTeam.team),
        )
        .order_by(Round.seq, Debate.external_id)
    )
    if tournament_id is not None:
        stmt = stmt.where(Debate.tournament_id == tournament_id)
    debates = (await session.execute(stmt)).scalars().all()

    max_seq_by_tournament: dict[int, int | None] = {}
    pending: list[PendingEliminationDebate] = []
    for debate in debates:
        tid = debate.tournament_id
        if tid not in max_seq_by_tournament:
            max_seq_by_tournament[tid] = await _max_elimination_seq(session, tid)
        is_final = debate.round.seq == max_seq_by_tournament[tid]

        missing = (
            any(dt.rank_in_debate is None for dt in debate.teams)
            if is_final
            else any(dt.advanced is None for dt in debate.teams)
        )
        if missing:
            pending.append(
                PendingEliminationDebate(debate=debate, round=debate.round, is_final=is_final)
            )
    return pending


async def _load_debate_with_teams(session: AsyncSession, debate_id: int) -> Debate | None:
    stmt = (
        select(Debate)
        .where(Debate.id == debate_id)
        .options(
            selectinload(Debate.round),
            selectinload(Debate.teams).selectinload(DebateTeam.team),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def apply_manual_champion(
    session: AsyncSession, debate_id: int, champion_team_id: int
) -> Debate:
    """Marks `champion_team_id` as the winner of the Grand Final debate `debate_id`, and sets it
    as the tournament's champion so BetType.CHAMPION markets can settle against it."""
    debate = await _load_debate_with_teams(session, debate_id)
    if debate is None:
        raise ManualResultError("Debate not found")

    team_ids = {dt.team_id for dt in debate.teams}
    if champion_team_id not in team_ids:
        raise ManualResultError("champion_team_id is not a team in this debate")

    for dt in debate.teams:
        dt.rank_in_debate = 1 if dt.team_id == champion_team_id else None
        dt.advanced = dt.team_id == champion_team_id

    debate.status = DebateStatus.CONFIRMED

    tournament = await session.get(Tournament, debate.tournament_id)
    if tournament is not None:
        tournament.champion_team_id = champion_team_id

    await session.flush()
    return debate


async def apply_manual_advancing_teams(
    session: AsyncSession, debate_id: int, advancing_team_ids: list[int]
) -> Debate:
    """Marks which teams advanced out of a (non-final) elimination debate."""
    debate = await _load_debate_with_teams(session, debate_id)
    if debate is None:
        raise ManualResultError("Debate not found")

    team_ids = {dt.team_id for dt in debate.teams}
    unknown = set(advancing_team_ids) - team_ids
    if unknown:
        raise ManualResultError(f"team_ids {sorted(unknown)} are not in this debate")
    if not advancing_team_ids:
        raise ManualResultError("advancing_team_ids must not be empty")

    for dt in debate.teams:
        dt.advanced = dt.team_id in advancing_team_ids

    debate.status = DebateStatus.CONFIRMED
    await session.flush()
    return debate
