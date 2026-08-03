"""Historical win rate by BP position (OG/OO/CG/CO), crossed with round stage.

See CNADE 2026 Roadmap Pieza 2b: this is the cheap half of the backfill -- unlike circuit
identity (services.circuit_identity_service), it needs no name matching at all. Position and
round stage already live on every DebateTeam/Round row, tournament-scoped or not, so this reads
directly off whatever tournaments (current or backfilled) are in the database.

Deliberately doesn't touch odds pricing itself -- see app.domain.odds.apply_positional_adjustment
for the pure blending function this feeds. Wiring that into the live quote_odds/market_board
pricing paths is a separate, careful pass (those two have to stay in lockstep, per
odds_service._round_winner_odds's own docstring), not bundled in with computing the numbers.
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BPPosition, RoundStage
from app.models.rounds import Debate, DebateTeam, Round

# Returned for a position with no observed debates yet -- an even 1-in-4 share, the same "no
# signal" value apply_positional_adjustment treats as a guaranteed no-op.
NO_DATA_WIN_RATE = 0.25


async def compute_positional_win_rates(
    session: AsyncSession, *, stage: RoundStage
) -> dict[BPPosition, float]:
    """Fraction of debates a team in each BP position finished a winner, across every tournament
    in the database, filtered to `stage`.

    "Winner" means different things by stage, matching how `top_n_probabilities`/`_advancing_count`
    already frame the same distinction elsewhere: in a preliminary debate exactly one team ranks
    1st; in an elimination debate 1 or 2 teams ADVANCE (DebateTeam.advanced), regardless of how
    many total teams the bracket eventually crowns.
    """
    # rank_in_debate and advanced are populated independently (see services.ingestion's
    # "rank_in_debate is not None or advanced is not None" completeness check) -- gate each
    # stage on whichever field is the one that's actually judged for it, or an unjudged debate's
    # NULL would silently count as a loss instead of being excluded.
    if stage == RoundStage.PRELIMINARY:
        won = DebateTeam.rank_in_debate == 1
        judged = DebateTeam.rank_in_debate.is_not(None)
    else:
        won = DebateTeam.advanced.is_(True)
        judged = DebateTeam.advanced.is_not(None)

    stmt = (
        select(DebateTeam.position, won)
        .join(Debate, DebateTeam.debate_id == Debate.id)
        .join(Round, Debate.round_id == Round.id)
        .where(Round.stage == stage, judged)
    )
    rows = (await session.execute(stmt)).all()

    wins: dict[BPPosition, int] = defaultdict(int)
    totals: dict[BPPosition, int] = defaultdict(int)
    for position, is_win in rows:
        totals[position] += 1
        if is_win:
            wins[position] += 1

    return {
        position: (wins[position] / totals[position] if totals[position] else NO_DATA_WIN_RATE)
        for position in BPPosition
    }
