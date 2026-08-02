"""Derives a Tournament's overall status/champion from its own ingested Round/Debate data.

Nothing here is scraped directly -- CalicoTab has no single "is the tournament finished" flag
we can read, so this infers it from what we already ingested. Important subtlety: the site's
round-navigation menu lists EVERY configured round (including elimination rounds) from the
very first scrape, long before they're drawn or played -- so "does an elimination round exist"
is not a usable signal. What matters is whether an elimination round has actually been JUDGED
(has a debate with team placements), not whether it merely appears on the schedule.
"""

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Debate, DebateTeam, Round, Tournament
from app.models.enums import RoundStage, RoundStatus, TournamentStatus


async def get_current_round(session: AsyncSession, tournament_id: int) -> Round | None:
    """The round the tournament is actually AT right now: the highest-seq RELEASED round (a
    published draw still being debated), else the highest-seq COMPLETED round, else the
    lowest-seq round of any status (a tournament that hasn't started yet)."""
    rounds = (
        (
            await session.execute(
                select(Round).where(Round.tournament_id == tournament_id).order_by(Round.seq)
            )
        )
        .scalars()
        .all()
    )
    if not rounds:
        return None
    released = [r for r in rounds if r.status == RoundStatus.RELEASED]
    if released:
        return released[-1]
    completed = [r for r in rounds if r.status == RoundStatus.COMPLETED]
    if completed:
        return completed[-1]
    return rounds[0]


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "tournament"


async def _unique_slug(session: AsyncSession, base_slug: str) -> str:
    """Appends `-2`, `-3`, ... until the slug doesn't collide with an existing tournament --
    `Tournament.slug` is globally unique, but the API only takes a human-readable `name`, so a
    slug has to be derived rather than supplied by the client."""
    candidate = base_slug
    suffix = 2
    while (
        await session.execute(select(Tournament.id).where(Tournament.slug == candidate))
    ).scalar_one_or_none() is not None:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    return candidate


async def create_tournament(
    session: AsyncSession,
    *,
    name: str,
    source_base_url: str,
    source_slug: str,
    timezone: str,
) -> Tournament:
    """Creates a Tournament row, deriving its unique `slug` from `name` since the API contract
    doesn't ask the client for one directly (see `Tournament.slug` vs. `source_slug`)."""
    slug = await _unique_slug(session, _slugify(name))
    tournament = Tournament(
        name=name,
        slug=slug,
        source_base_url=source_base_url,
        source_slug=source_slug,
        timezone=timezone,
    )
    session.add(tournament)
    await session.flush()
    return tournament


async def refresh_tournament_status(session: AsyncSession, tournament: Tournament) -> None:
    final_round = (
        await session.execute(
            select(Round)
            .where(Round.tournament_id == tournament.id, Round.stage == RoundStage.ELIMINATION)
            .order_by(Round.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if final_round is not None:
        champion_team_id = await _final_round_champion(session, final_round)
        if champion_team_id is not None:
            tournament.champion_team_id = champion_team_id
            tournament.status = TournamentStatus.COMPLETED
            # A completed tournament has no more live data to fetch -- autoscrape would
            # otherwise keep polling it forever (see scrape_all_active_tournaments_async's
            # is_active filter). This is what makes adding a historical/backfill tab (paste the
            # URL, get one full scrape, done) genuinely "fire and forget" instead of needing an
            # admin to remember to flip it inactive by hand afterward. An admin can still
            # reactivate manually (the existing toggle in /admin/tournaments) if a result is
            # ever corrected after the fact.
            tournament.is_active = False
            return

    any_elimination_result = await _has_any_judged_result(
        session, tournament.id, stage=RoundStage.ELIMINATION
    )
    if any_elimination_result:
        tournament.status = TournamentStatus.ELIMINATIONS
        return

    any_preliminary_result = await _has_any_judged_result(
        session, tournament.id, stage=RoundStage.PRELIMINARY
    )
    tournament.status = (
        TournamentStatus.IN_PROGRESS if any_preliminary_result else TournamentStatus.UPCOMING
    )


async def _has_any_judged_result(
    session: AsyncSession, tournament_id: int, *, stage: RoundStage
) -> bool:
    result = (
        await session.execute(
            select(DebateTeam.id)
            .join(Debate, DebateTeam.debate_id == Debate.id)
            .join(Round, Debate.round_id == Round.id)
            .where(
                Round.tournament_id == tournament_id,
                Round.stage == stage,
                or_(DebateTeam.rank_in_debate.is_not(None), DebateTeam.advanced.is_not(None)),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return result is not None


async def _final_round_champion(session: AsyncSession, final_round: Round) -> int | None:
    """The Grand Final is a single debate; its winner is the champion, once judged.

    `final_round` here just means "the highest-seq ELIMINATION round ingested so far" -- until
    the real Grand Final has actually been drawn, that's an earlier out-round instead (octos,
    quarters, semis), which has MULTIPLE debates with 2-of-4 teams `advanced == True` per room.
    Querying those the single-champion way below would find 2+ matching rows and blow up
    `scalar_one_or_none()`, so this only proceeds once the round has settled down to exactly the
    Grand Final's one debate.

    Finals published with public ballots rank the winner `rank_in_debate == 1`; the more common
    case (elimination rounds don't get public ballots -- see parsers.py) instead marks the winner
    via `advanced == True` ("Advancing" vs. "Eliminated"). Exactly one of the two signals is
    populated per debate, never both, so combining them with `or_` is unambiguous.
    """
    debate_ids = (
        (await session.execute(select(Debate.id).where(Debate.round_id == final_round.id)))
        .scalars()
        .all()
    )
    if len(debate_ids) != 1:
        return None
    return (
        await session.execute(
            select(DebateTeam.team_id).where(
                DebateTeam.debate_id == debate_ids[0],
                or_(DebateTeam.rank_in_debate == 1, DebateTeam.advanced.is_(True)),
            )
        )
    ).scalar_one_or_none()
