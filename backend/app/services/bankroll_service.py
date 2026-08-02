"""Per-tournament bankroll (CNADE 2026 Roadmap Pieza 3): `TournamentBalance` replaces the old
global `User.balance`. Every consumer of "how many tokens does this user have" -- betting,
transfers, prizes, the admin economy view -- goes through `get_or_create_tournament_balance`
below, never constructs or looks up `TournamentBalance` directly.

A new tournament balance does NOT start flat at `STARTING_BALANCE` -- it carries a bonus or
penalty from the user's previous COMPLETED tournament's final balance (ROI-proportional, capped
both ways). This is deliberately the OPPOSITE of "cancha pareja" (the original reason balance
was split per tournament in the first place) -- a product decision Paranoid reaffirmed once
already flagged, not an oversight. See the vault note "Bankroll por torneo (Pieza 3)" under
02 - Claim/How It Works/ for the full rationale before touching BONUS_ROI_FACTOR or the caps.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.betting import STARTING_BALANCE, TournamentBalance, User
from app.models.enums import TournamentStatus
from app.models.tournament import Tournament

# What fraction of a user's previous-tournament ROI carries into their next tournament's
# starting balance.
BONUS_ROI_FACTOR = 0.5
# Floor/ceiling on the resulting starting balance -- keeps one exceptional (or disastrous)
# tournament from defining every tournament after it.
MIN_STARTING_BALANCE = 50.0
MAX_STARTING_BALANCE = 200.0


async def _previous_completed_balance(
    session: AsyncSession, user_id: int, exclude_tournament_id: int
) -> float | None:
    """The user's final balance in their most recent OTHER tournament, but only if that
    tournament is already COMPLETED -- an in-progress tournament's balance isn't final yet, so
    it doesn't count as "the previous result" (falls back to no bonus, same as a user's very
    first tournament). None if the user has no COMPLETED tournament balance at all.

    Ordered by Tournament.created_at (there's no explicit tournament start date in the schema)
    -- this only matters once a backfilled historical tournament has real economy activity of
    its own, which isn't the case yet: today's only completed tournament with real bets is
    CMUDE 2026.
    """
    stmt = (
        select(TournamentBalance.balance)
        .join(Tournament, TournamentBalance.tournament_id == Tournament.id)
        .where(
            TournamentBalance.user_id == user_id,
            TournamentBalance.tournament_id != exclude_tournament_id,
            Tournament.status == TournamentStatus.COMPLETED,
        )
        .order_by(Tournament.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _starting_balance_for(previous_balance: float | None) -> float:
    if previous_balance is None:
        return STARTING_BALANCE
    roi = (previous_balance - STARTING_BALANCE) / STARTING_BALANCE
    bonus = roi * BONUS_ROI_FACTOR
    return max(MIN_STARTING_BALANCE, min(MAX_STARTING_BALANCE, STARTING_BALANCE + bonus))


async def get_or_create_tournament_balance(
    session: AsyncSession, user: User, tournament_id: int
) -> TournamentBalance:
    """The single entry point for "this user's wallet in this tournament". Lazily creates the
    row the first time a user touches this tournament's economy (a bet, a transfer, a prize),
    applying the ROI carryover from their last COMPLETED tournament if one exists. A second call
    for the same (user, tournament) always returns the same row -- never creates a duplicate.

    Callers that create a NEW row are responsible for committing/flushing the session same as
    any other write (this only flushes, so the row is visible within the same transaction).
    """
    existing = (
        await session.execute(
            select(TournamentBalance).where(
                TournamentBalance.tournament_id == tournament_id,
                TournamentBalance.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    previous_balance = await _previous_completed_balance(session, user.id, tournament_id)
    tournament_balance = TournamentBalance(
        tournament_id=tournament_id,
        user_id=user.id,
        balance=_starting_balance_for(previous_balance),
    )
    session.add(tournament_balance)
    await session.flush()
    return tournament_balance
