import datetime

from app.models import Tournament, User
from app.models.betting import BetMarket, Prediction, TournamentBalance
from app.models.enums import BetMarketStatus, BetType, PredictionStatus, TournamentStatus, UserRole
from app.services.game_economy_service import compute_game_economy, compute_market_payout_spread

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


async def _make_user(
    db_session, email: str, *, tournament: Tournament | None = None, balance: float | None = None
) -> User:
    user = User(email=email, password_hash="x", display_name=email, role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    if tournament is not None and balance is not None:
        db_session.add(
            TournamentBalance(tournament_id=tournament.id, user_id=user.id, balance=balance)
        )
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


async def test_compute_game_economy_separates_open_and_settled(db_session) -> None:
    tournament = await _make_tournament(db_session)
    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    alice = await _make_user(db_session, "alice@example.com", tournament=tournament, balance=200.0)
    bob = await _make_user(db_session, "bob@example.com", tournament=tournament, balance=70.0)

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

    summary = await compute_game_economy(db_session, tournament.id)
    assert summary.total_staked_settled == 80.0
    assert summary.total_paid_out == 150.0
    # 150 paid out on 80 staked settled -- the platform net-minted 70 tokens on this round.
    assert summary.net_token_inflation == 150.0 - 80.0
    assert summary.total_staked_open == 0.0
    assert summary.settled_predictions_count == 2
    assert summary.open_predictions_count == 0
    assert summary.active_bettors_count == 2
    assert summary.tokens_in_circulation == 270.0  # 200 + 70, scoped to this tournament


async def test_compute_market_payout_spread_mutually_exclusive_bounds(db_session) -> None:
    tournament = await _make_tournament(db_session)
    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    # Pool = 100. If team 1 wins: 50*3=150 paid out, nets 100-150=-50 (worst case, net token
    # destruction of 50). If team 2 wins: 50*2=100 paid out, nets 100-100=0. If neither wins,
    # nothing is paid out: nets +100 (best case).
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

    spread = await compute_market_payout_spread(db_session, market)
    assert spread is not None
    assert spread.pool_total == 100.0
    assert spread.worst_case == -50.0
    assert spread.best_case == 100.0


async def test_compute_market_payout_spread_team_break_independent_bounds(db_session) -> None:
    tournament = await _make_tournament(db_session)
    category_market = await _make_market(
        db_session, tournament, BetType.TEAM_BREAK, target_break_category_id=1
    )
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    # Pool = 30. Independent props: if BOTH backed teams break, 10*2 + 20*2 = 60 paid out,
    # nets 30-60=-30 (worst case). If NEITHER breaks, nothing paid out: +30 (best case).
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

    spread = await compute_market_payout_spread(db_session, category_market)
    assert spread is not None
    assert spread.pool_total == 30.0
    assert spread.worst_case == -30.0
    assert spread.best_case == 30.0


async def test_compute_market_payout_spread_none_when_no_open_predictions(db_session) -> None:
    tournament = await _make_tournament(db_session)
    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    await db_session.commit()

    assert await compute_market_payout_spread(db_session, market) is None
