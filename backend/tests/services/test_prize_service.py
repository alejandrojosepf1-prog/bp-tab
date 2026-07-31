import datetime

import pytest
from sqlalchemy import select

from app.models import BetMarket, Prediction, PrizeEntry, PrizeEvent, Tournament, User
from app.models.enums import (
    BetType,
    PredictionStatus,
    PrizeEventStatus,
    PrizeEventType,
    TournamentStatus,
    UserRole,
)
from app.services.prize_service import (
    InsufficientBalanceError,
    PrizeEventError,
    enter_raffle,
    queue_manual_award,
    resolve_prize_event,
)

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


_tournament_seq = 0


async def _make_tournament(db_session) -> Tournament:
    global _tournament_seq
    _tournament_seq += 1
    tournament = Tournament(
        name=f"T{_tournament_seq}", slug=f"t{_tournament_seq}",
        source_base_url="https://x", source_slug=f"o{_tournament_seq}",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _make_user(db_session, email: str, *, balance: float = 100.0) -> User:
    user = User(
        email=email, password_hash="x", display_name=email, role=UserRole.USER,
        balance=balance,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_event(
    db_session, tournament: Tournament, event_type: PrizeEventType, **kwargs
) -> PrizeEvent:
    event = PrizeEvent(
        tournament_id=tournament.id, type=event_type, title="Prize",
        config=kwargs.pop("config", {}), **kwargs,
    )
    db_session.add(event)
    await db_session.flush()
    return event


# --- manual_award -------------------------------------------------------------------------


async def test_manual_award_credits_balance_only_after_resolve(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(db_session, tournament, PrizeEventType.MANUAL_AWARD)
    alice = await _make_user(db_session, "alice@example.com", balance=50.0)
    await db_session.commit()

    await queue_manual_award(db_session, event, alice.id, 25.0)
    await db_session.commit()
    await db_session.refresh(alice)
    assert alice.balance == 50.0  # not credited yet -- only queued

    await resolve_prize_event(db_session, event)
    await db_session.commit()
    await db_session.refresh(alice)
    assert alice.balance == 75.0
    assert event.status == PrizeEventStatus.RESOLVED


async def test_manual_award_requeue_replaces_not_stacks(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(db_session, tournament, PrizeEventType.MANUAL_AWARD)
    alice = await _make_user(db_session, "alice@example.com")
    await db_session.commit()

    await queue_manual_award(db_session, event, alice.id, 10.0)
    await queue_manual_award(db_session, event, alice.id, 30.0)  # admin fixes a typo
    await db_session.commit()

    await resolve_prize_event(db_session, event)
    await db_session.commit()
    await db_session.refresh(alice)
    assert alice.balance == pytest.approx(130.0)  # 100 start + 30, NOT +10+30


async def test_manual_award_rejects_wrong_type(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(db_session, tournament, PrizeEventType.RAFFLE)
    alice = await _make_user(db_session, "alice@example.com")
    await db_session.commit()
    with pytest.raises(PrizeEventError):
        await queue_manual_award(db_session, event, alice.id, 10.0)


async def test_resolving_twice_raises(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(db_session, tournament, PrizeEventType.MANUAL_AWARD)
    await db_session.commit()
    await resolve_prize_event(db_session, event)
    await db_session.commit()
    with pytest.raises(PrizeEventError):
        await resolve_prize_event(db_session, event)


# --- raffle --------------------------------------------------------------------------------


async def test_raffle_entry_charges_ticket_cost(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(
        db_session, tournament, PrizeEventType.RAFFLE,
        config={"num_winners": 1, "prize_per_winner": 50.0, "ticket_cost": 5.0},
    )
    alice = await _make_user(db_session, "alice@example.com", balance=100.0)
    await db_session.commit()

    await enter_raffle(db_session, event, alice, 3)
    await db_session.commit()
    await db_session.refresh(alice)
    assert alice.balance == pytest.approx(85.0)  # 100 - 3*5


async def test_raffle_re_entry_only_charges_the_difference(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(
        db_session, tournament, PrizeEventType.RAFFLE,
        config={"num_winners": 1, "prize_per_winner": 50.0, "ticket_cost": 5.0},
    )
    alice = await _make_user(db_session, "alice@example.com", balance=100.0)
    await db_session.commit()

    entry = await enter_raffle(db_session, event, alice, 3)
    await db_session.commit()
    entry2 = await enter_raffle(db_session, event, alice, 5)  # tops up 3 -> 5, charges 2 more
    await db_session.commit()
    await db_session.refresh(alice)

    assert entry.id == entry2.id  # same row, not a second entry
    assert entry2.tickets == 5
    assert alice.balance == pytest.approx(75.0)  # 100 - 3*5 - 2*5, NOT 100 - 3*5 - 5*5


async def test_raffle_entry_rejects_insufficient_balance(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(
        db_session, tournament, PrizeEventType.RAFFLE,
        config={"num_winners": 1, "prize_per_winner": 50.0, "ticket_cost": 100.0},
    )
    alice = await _make_user(db_session, "alice@example.com", balance=50.0)
    await db_session.commit()
    with pytest.raises(InsufficientBalanceError):
        await enter_raffle(db_session, event, alice, 1)


async def test_raffle_free_entry_when_no_ticket_cost(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(
        db_session, tournament, PrizeEventType.RAFFLE,
        config={"num_winners": 1, "prize_per_winner": 50.0},  # no ticket_cost -> free
    )
    alice = await _make_user(db_session, "alice@example.com", balance=10.0)
    await db_session.commit()
    await enter_raffle(db_session, event, alice, 5)
    await db_session.commit()
    await db_session.refresh(alice)
    assert alice.balance == 10.0  # untouched


async def test_raffle_entry_rejects_over_the_max_tickets_per_user_cap(db_session) -> None:
    """A free raffle with no cap lets anyone buy unlimited tickets, dominating the weighted
    draw -- max_tickets_per_user lets an admin close that off, for free or paid raffles alike."""
    tournament = await _make_tournament(db_session)
    event = await _make_event(
        db_session, tournament, PrizeEventType.RAFFLE,
        config={"num_winners": 1, "prize_per_winner": 50.0, "max_tickets_per_user": 3},
    )
    alice = await _make_user(db_session, "alice@example.com")
    await db_session.commit()
    with pytest.raises(PrizeEventError):
        await enter_raffle(db_session, event, alice, 4)


async def test_raffle_entry_allows_up_to_the_max_tickets_per_user_cap(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(
        db_session, tournament, PrizeEventType.RAFFLE,
        config={"num_winners": 1, "prize_per_winner": 50.0, "max_tickets_per_user": 3},
    )
    alice = await _make_user(db_session, "alice@example.com")
    await db_session.commit()
    entry = await enter_raffle(db_session, event, alice, 3)
    assert entry.tickets == 3


async def test_raffle_resolve_picks_exactly_num_winners_and_pays_them(db_session) -> None:
    tournament = await _make_tournament(db_session)
    event = await _make_event(
        db_session, tournament, PrizeEventType.RAFFLE,
        config={"num_winners": 2, "prize_per_winner": 100.0},
    )
    users = [await _make_user(db_session, f"u{i}@example.com", balance=0.0) for i in range(5)]
    await db_session.commit()
    for u in users:
        await enter_raffle(db_session, event, u, 1)
    await db_session.commit()

    await resolve_prize_event(db_session, event)
    await db_session.commit()

    entries = (
        (
            await db_session.execute(
                select(PrizeEntry).where(PrizeEntry.prize_event_id == event.id)
            )
        )
        .scalars()
        .all()
    )
    winners = [e for e in entries if e.awarded_amount and e.awarded_amount > 0]
    losers = [e for e in entries if not e.awarded_amount]
    assert len(winners) == 2
    assert len(losers) == 3
    assert all(e.awarded_amount == 100.0 for e in winners)
    assert event.rng_seed is not None

    for u in users:
        await db_session.refresh(u)
    total_paid = sum(u.balance for u in users)
    assert total_paid == pytest.approx(200.0)  # exactly 2 winners * 100, no more no less


async def test_raffle_more_tickets_gives_more_wins_over_many_seeds(db_session) -> None:
    """Statistical sanity check, not a single-draw assertion (a single seed could go either
    way): across many independently-seeded events, the heavy favorite should win noticeably
    more often than a 1-ticket entrant."""
    tournament = await _make_tournament(db_session)
    heavy_wins = 0
    trials = 30
    for i in range(trials):
        event = await _make_event(
            db_session, tournament, PrizeEventType.RAFFLE,
            config={"num_winners": 1, "prize_per_winner": 10.0},
        )
        heavy = await _make_user(db_session, f"heavy{i}@example.com")
        light = await _make_user(db_session, f"light{i}@example.com")
        await db_session.commit()
        await enter_raffle(db_session, event, heavy, 9)
        await enter_raffle(db_session, event, light, 1)
        await db_session.commit()
        await resolve_prize_event(db_session, event)
        await db_session.commit()
        await db_session.refresh(heavy)
        if heavy.balance > 100.0:
            heavy_wins += 1
    # With a true 9:1 weighting, heavy should win ~90% of the time -- assert comfortably above
    # the 50% a broken (unweighted) implementation would produce.
    assert heavy_wins > trials * 0.7


# --- activity_bonus -------------------------------------------------------------------------


async def _make_prediction(db_session, market: BetMarket, user: User, *, locked_at) -> Prediction:
    pred = Prediction(
        bet_market_id=market.id, user_id=user.id, entity_key="__market__",
        payload={}, locked_at=locked_at, status=PredictionStatus.OPEN,
        stake_amount=10.0, odds=2.0,
    )
    db_session.add(pred)
    await db_session.flush()
    return pred


async def test_activity_bonus_credits_only_users_who_bet_in_window(db_session) -> None:
    tournament = await _make_tournament(db_session)
    other_tournament = await _make_tournament(db_session)
    market = BetMarket(
        tournament_id=tournament.id, bet_type=BetType.CHAMPION, label="m",
        opens_at=NOW, closes_at=NOW, points_rule={},
    )
    other_market = BetMarket(
        tournament_id=other_tournament.id, bet_type=BetType.CHAMPION, label="m2",
        opens_at=NOW, closes_at=NOW, points_rule={},
    )
    db_session.add_all([market, other_market])
    await db_session.flush()

    active = await _make_user(db_session, "active@example.com", balance=0.0)
    inactive = await _make_user(db_session, "inactive@example.com", balance=0.0)
    wrong_tournament = await _make_user(db_session, "wrong@example.com", balance=0.0)
    await db_session.commit()

    event = await _make_event(
        db_session, tournament, PrizeEventType.ACTIVITY_BONUS,
        config={"bonus_amount": 15.0},
        # created_at comes from the DB's real server_default=func.now(), NOT the frozen `NOW`
        # constant -- closes_at has to be relative to actual wall-clock time too, or the window
        # [created_at, closes_at] would be empty/inverted.
        closes_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
    )
    await db_session.commit()

    await _make_prediction(db_session, market, active, locked_at=event.created_at)
    await _make_prediction(db_session, other_market, wrong_tournament, locked_at=event.created_at)
    await db_session.commit()

    await resolve_prize_event(db_session, event)
    await db_session.commit()

    await db_session.refresh(active)
    await db_session.refresh(inactive)
    await db_session.refresh(wrong_tournament)
    assert active.balance == 15.0
    assert inactive.balance == 0.0
    assert wrong_tournament.balance == 0.0  # bet on a DIFFERENT tournament, doesn't qualify


async def test_activity_bonus_ignores_predictions_outside_the_window(db_session) -> None:
    tournament = await _make_tournament(db_session)
    market = BetMarket(
        tournament_id=tournament.id, bet_type=BetType.CHAMPION, label="m",
        opens_at=NOW, closes_at=NOW, points_rule={},
    )
    db_session.add(market)
    await db_session.flush()
    user = await _make_user(db_session, "late@example.com", balance=0.0)
    await db_session.commit()

    event = await _make_event(
        db_session, tournament, PrizeEventType.ACTIVITY_BONUS,
        config={"bonus_amount": 15.0},
        closes_at=NOW,
    )
    await db_session.commit()
    # Bet placed AFTER the event's window closed -- shouldn't count.
    late = event.closes_at + datetime.timedelta(hours=1)
    await _make_prediction(db_session, market, user, locked_at=late)
    await db_session.commit()

    await resolve_prize_event(db_session, event)
    await db_session.commit()
    await db_session.refresh(user)
    assert user.balance == 0.0
