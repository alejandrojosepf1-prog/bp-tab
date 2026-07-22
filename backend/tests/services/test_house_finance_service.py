import datetime

from app.models import Tournament, User
from app.models.betting import BetMarket, Prediction
from app.models.enums import BetMarketStatus, BetType, PredictionStatus, TournamentStatus, UserRole
from app.services.house_finance_service import compute_house_summary, compute_market_exposure

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


async def _make_tournament(db_session) -> Tournament:
    tournament = Tournament(
        name="Finance Cup",
        slug="finance-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _make_user(db_session, email: str) -> User:
    user = User(email=email, password_hash="x", display_name=email, role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_market(db_session, tournament, bet_type, **kwargs) -> BetMarket:
    market = BetMarket(
        tournament_id=tournament.id,
        bet_type=bet_type,
        label="test market",
        opens_at=NOW,
        closes_at=NOW,
        points_rule={},
        status=BetMarketStatus.OPEN,
        **kwargs,
    )
    db_session.add(market)
    await db_session.flush()
    return market


def _prediction(market, user, *, entity_key, payload, stake, odds, status, points_awarded=None):
    return Prediction(
        bet_market_id=market.id,
        user_id=user.id,
        entity_key=entity_key,
        payload=payload,
        locked_at=NOW,
        stake_amount=stake,
        odds=odds,
        status=status,
        points_awarded=points_awarded,
    )


async def test_compute_house_summary_separates_open_and_settled(db_session) -> None:
    tournament = await _make_tournament(db_session)
    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    db_session.add_all(
        [
            # Settled: alice won (paid 150 on a 50 stake), bob lost (paid 0 on a 30 stake).
            _prediction(
                market, alice, entity_key="__market__", payload={"team_id": 1}, stake=50.0,
                odds=3.0, status=PredictionStatus.SETTLED, points_awarded=150.0,
            ),
            _prediction(
                market, bob, entity_key="__market__", payload={"team_id": 2}, stake=30.0,
                odds=2.0, status=PredictionStatus.SETTLED, points_awarded=0.0,
            ),
        ]
    )
    await db_session.commit()

    summary = await compute_house_summary(db_session, tournament.id)
    assert summary.total_staked_settled == 80.0
    assert summary.total_paid_out == 150.0
    assert summary.realized_net_profit == 80.0 - 150.0  # house lost 70 on this round
    assert summary.total_staked_open == 0.0


async def test_compute_market_exposure_mutually_exclusive_bounds(db_session) -> None:
    tournament = await _make_tournament(db_session)
    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    # Pool = 100. If team 1 wins: house pays 50*3=150, nets 100-150=-50 (worst case).
    # If team 2 wins: house pays 50*2=100, nets 100-100=0.
    # If neither wins (someone else does): house keeps the full pool, nets +100 (best case).
    db_session.add_all(
        [
            _prediction(
                market, alice, entity_key="__market__", payload={"team_id": 1}, stake=50.0,
                odds=3.0, status=PredictionStatus.OPEN,
            ),
            _prediction(
                market, bob, entity_key="__market__", payload={"team_id": 2}, stake=50.0,
                odds=2.0, status=PredictionStatus.OPEN,
            ),
        ]
    )
    await db_session.commit()

    exposure = await compute_market_exposure(db_session, market)
    assert exposure is not None
    assert exposure.pool_total == 100.0
    assert exposure.worst_case == -50.0
    assert exposure.best_case == 100.0


async def test_compute_market_exposure_team_break_independent_bounds(db_session) -> None:
    tournament = await _make_tournament(db_session)
    category_market = await _make_market(
        db_session, tournament, BetType.TEAM_BREAK, target_break_category_id=1
    )
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    # Pool = 30. Independent props: if BOTH backed teams break, house pays 10*2 + 20*2 = 60,
    # nets 30-60=-30 (worst case). If NEITHER breaks, house keeps the pool: +30 (best case).
    db_session.add_all(
        [
            _prediction(
                category_market, alice, entity_key="team:1", payload={"team_id": 1}, stake=10.0,
                odds=2.0, status=PredictionStatus.OPEN,
            ),
            _prediction(
                category_market, bob, entity_key="team:2", payload={"team_id": 2}, stake=20.0,
                odds=2.0, status=PredictionStatus.OPEN,
            ),
        ]
    )
    await db_session.commit()

    exposure = await compute_market_exposure(db_session, category_market)
    assert exposure is not None
    assert exposure.pool_total == 30.0
    assert exposure.worst_case == -30.0
    assert exposure.best_case == 30.0


async def test_compute_market_exposure_none_when_no_open_predictions(db_session) -> None:
    tournament = await _make_tournament(db_session)
    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    await db_session.commit()

    assert await compute_market_exposure(db_session, market) is None
