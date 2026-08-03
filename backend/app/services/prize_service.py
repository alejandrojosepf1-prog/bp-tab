"""Runs the three prize-event mechanics an admin can use to hand out tokens outside of betting
outcomes -- a way to keep the game rewarding for participation, not just for correct calls.

Three types, one shared lifecycle (OPEN -> RESOLVED, one-way -- see `resolve_prize_event`):

  - MANUAL_AWARD: the admin queues named awards (`queue_manual_award`), each with its own
    amount. Nothing users do themselves; resolving credits every queued entry at once.
  - RAFFLE: users buy in with `enter_raffle` (tickets, optionally costing balance). Resolving
    draws `num_winners` winners weighted by ticket count, using a seeded RNG persisted on the
    event row (`rng_seed`) so the draw is independently reproducible -- nobody has to take the
    admin's word for who won, the same way `break_predictor`'s seeded simulations work.
  - ACTIVITY_BONUS: no entries at all until resolve -- resolving itself computes who qualified
    (placed at least one prediction on this tournament between the event's creation and
    `closes_at`) and credits every qualifying user the flat bonus, creating their entries then.
"""

import datetime
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BetMarket, Prediction, PrizeEntry, PrizeEvent, User
from app.models.enums import PrizeEventStatus, PrizeEventType
from app.services.bankroll_service import get_or_create_tournament_balance


class PrizeEventError(Exception):
    """Raised when an operation doesn't fit this event's type/status/config -- the router maps
    this to a 400."""


class InsufficientBalanceError(Exception):
    """Raised when a raffle entry's ticket cost exceeds the entrant's balance."""


def _require_type(event: PrizeEvent, expected: PrizeEventType) -> None:
    if event.type != expected:
        raise PrizeEventError(f"this operation only applies to {expected.value} events")


def _require_open(event: PrizeEvent) -> None:
    if event.status != PrizeEventStatus.OPEN:
        raise PrizeEventError("this prize event is already resolved")


async def _existing_entry(
    session: AsyncSession, prize_event_id: int, user_id: int
) -> PrizeEntry | None:
    return (
        await session.execute(
            select(PrizeEntry).where(
                PrizeEntry.prize_event_id == prize_event_id, PrizeEntry.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def queue_manual_award(
    session: AsyncSession, event: PrizeEvent, user_id: int, amount: float
) -> PrizeEntry:
    """Admin-only: names a user and an amount to credit once this event resolves. Calling this
    again for the same user REPLACES the queued amount rather than stacking a second award --
    an admin fixing a typo shouldn't have to delete a row first."""
    _require_type(event, PrizeEventType.MANUAL_AWARD)
    _require_open(event)
    if amount <= 0:
        raise PrizeEventError("amount must be positive")

    existing = await _existing_entry(session, event.id, user_id)
    if existing is not None:
        existing.awarded_amount = amount
        return existing
    entry = PrizeEntry(prize_event_id=event.id, user_id=user_id, awarded_amount=amount)
    session.add(entry)
    await session.flush()
    return entry


async def enter_raffle(
    session: AsyncSession, event: PrizeEvent, user: User, tickets: int
) -> PrizeEntry:
    """A user buys (or is given, if `ticket_cost` is unset/zero) `tickets` entries into this
    raffle. Re-entering tops up to the new total and only charges for the DIFFERENCE, so
    changing your mind about how many tickets to buy never double-charges."""
    _require_type(event, PrizeEventType.RAFFLE)
    _require_open(event)
    if tickets <= 0:
        raise PrizeEventError("tickets must be positive")

    max_tickets = event.config.get("max_tickets_per_user")
    if max_tickets is not None and tickets > max_tickets:
        raise PrizeEventError(f"max {int(max_tickets)} tickets per person for this raffle")

    ticket_cost = float(event.config.get("ticket_cost") or 0)
    existing = await _existing_entry(session, event.id, user.id)
    already_owned = existing.tickets if existing else 0

    if ticket_cost > 0:
        extra_cost = (tickets - already_owned) * ticket_cost
        if extra_cost > 0:
            tournament_balance = await get_or_create_tournament_balance(
                session, user, event.tournament_id
            )
            if tournament_balance.balance < extra_cost:
                raise InsufficientBalanceError(
                    f"insufficient balance: have {tournament_balance.balance:.2f}, "
                    f"need {extra_cost:.2f}"
                )
            tournament_balance.balance -= extra_cost

    if existing is not None:
        existing.tickets = tickets
        return existing
    entry = PrizeEntry(prize_event_id=event.id, user_id=user.id, tickets=tickets)
    session.add(entry)
    await session.flush()
    return entry


async def resolve_prize_event(session: AsyncSession, event: PrizeEvent) -> PrizeEvent:
    """Finalizes an OPEN event: credits balances per the type's own rule (see module
    docstring), then flips it to RESOLVED. Raises PrizeEventError if it's already resolved --
    resolution is one-way, exactly like settling a BetMarket."""
    _require_open(event)

    if event.type == PrizeEventType.MANUAL_AWARD:
        await _resolve_manual_award(session, event)
    elif event.type == PrizeEventType.RAFFLE:
        await _resolve_raffle(session, event)
    else:
        await _resolve_activity_bonus(session, event)

    event.status = PrizeEventStatus.RESOLVED
    event.resolved_at = datetime.datetime.now(datetime.timezone.utc)
    await session.flush()
    return event


async def _entries_for(session: AsyncSession, event_id: int) -> list[PrizeEntry]:
    return list(
        (
            await session.execute(select(PrizeEntry).where(PrizeEntry.prize_event_id == event_id))
        )
        .scalars()
        .all()
    )


async def _resolve_manual_award(session: AsyncSession, event: PrizeEvent) -> None:
    for entry in await _entries_for(session, event.id):
        if entry.awarded_amount and entry.awarded_amount > 0:
            user = await session.get(User, entry.user_id)
            if user is not None:
                tournament_balance = await get_or_create_tournament_balance(
                    session, user, event.tournament_id
                )
                tournament_balance.balance += entry.awarded_amount


async def _resolve_raffle(session: AsyncSession, event: PrizeEvent) -> None:
    entries = await _entries_for(session, event.id)
    num_winners = int(event.config.get("num_winners") or 1)
    prize_per_winner = float(event.config.get("prize_per_winner") or 0)

    seed = event.rng_seed or f"prize-event:{event.id}"
    event.rng_seed = seed
    rng = random.Random(seed)

    # Weighted sampling WITHOUT replacement at the user level: a ticket pool where each entrant
    # appears once per ticket owned, drawn one winner at a time and stripped of ALL of that
    # winner's tickets before the next draw -- so someone with more tickets has proportionally
    # better odds, but nobody can win twice.
    pool = [entry.user_id for entry in entries for _ in range(entry.tickets)]
    winners: set[int] = set()
    while pool and len(winners) < min(num_winners, len(entries)):
        pick = rng.choice(pool)
        winners.add(pick)
        pool = [uid for uid in pool if uid != pick]

    for entry in entries:
        won = entry.user_id in winners
        entry.awarded_amount = prize_per_winner if won else 0.0
        if won and prize_per_winner > 0:
            user = await session.get(User, entry.user_id)
            if user is not None:
                tournament_balance = await get_or_create_tournament_balance(
                    session, user, event.tournament_id
                )
                tournament_balance.balance += prize_per_winner


async def _resolve_activity_bonus(session: AsyncSession, event: PrizeEvent) -> None:
    bonus_amount = float(event.config.get("bonus_amount") or 0)
    if bonus_amount <= 0:
        return
    window_end = event.closes_at or datetime.datetime.now(datetime.timezone.utc)
    qualifying_user_ids = (
        (
            await session.execute(
                select(Prediction.user_id)
                .join(BetMarket, Prediction.bet_market_id == BetMarket.id)
                .where(
                    BetMarket.tournament_id == event.tournament_id,
                    Prediction.locked_at >= event.created_at,
                    Prediction.locked_at <= window_end,
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    for user_id in qualifying_user_ids:
        session.add(
            PrizeEntry(prize_event_id=event.id, user_id=user_id, awarded_amount=bonus_amount)
        )
        user = await session.get(User, user_id)
        if user is not None:
            tournament_balance = await get_or_create_tournament_balance(
                session, user, event.tournament_id
            )
            tournament_balance.balance += bonus_amount
