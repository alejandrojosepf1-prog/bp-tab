import datetime

from app.models import Tournament, User
from app.models.betting import BetMarket, Prediction, TournamentBalance
from app.models.enums import BetType, PredictionStatus, TournamentStatus, UserRole
from app.services.leaderboard_service import compute_leaderboard

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


async def _make_tournament(db_session, name: str) -> Tournament:
    tournament = Tournament(
        name=name,
        slug=name.lower().replace(" ", "-"),
        source_base_url="https://example.calicotab.com",
        source_slug=name.lower(),
        status=TournamentStatus.COMPLETED,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _make_market(db_session, tournament: Tournament) -> BetMarket:
    market = BetMarket(
        tournament_id=tournament.id, bet_type=BetType.CHAMPION, label="m",
        opens_at=NOW, closes_at=NOW, points_rule={},
    )
    db_session.add(market)
    await db_session.flush()
    return market


async def _make_user(
    db_session,
    email: str,
    display_name: str,
    *,
    tournament: Tournament | None = None,
    balance: float | None = None,
) -> User:
    user = User(email=email, password_hash="x", display_name=display_name, role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    if tournament is not None and balance is not None:
        db_session.add(
            TournamentBalance(tournament_id=tournament.id, user_id=user.id, balance=balance)
        )
        await db_session.flush()
    return user


def _settled_prediction(market, user, *, stake, points_awarded, entity_key="__market__"):
    return Prediction(
        bet_market_id=market.id, user_id=user.id, entity_key=entity_key,
        payload={"team_id": 1}, locked_at=NOW, stake_amount=stake, odds=points_awarded / stake
        if stake and points_awarded else 1.0,
        status=PredictionStatus.SETTLED, points_awarded=points_awarded,
    )


async def test_compute_leaderboard_sums_across_tournaments_when_unscoped(db_session) -> None:
    t1 = await _make_tournament(db_session, "Cup One")
    t2 = await _make_tournament(db_session, "Cup Two")
    m1 = await _make_market(db_session, t1)
    m2 = await _make_market(db_session, t2)
    alice = await _make_user(db_session, "alice@x.com", "Alice", tournament=t1, balance=150.0)
    bob = await _make_user(db_session, "bob@x.com", "Bob", tournament=t1, balance=80.0)
    await db_session.commit()

    db_session.add_all(
        [
            _settled_prediction(m1, alice, stake=50.0, points_awarded=100.0),  # +50 net
            _settled_prediction(m2, alice, stake=30.0, points_awarded=50.0),  # +20 net
            _settled_prediction(m1, bob, stake=100.0, points_awarded=200.0),  # +100 net
        ]
    )
    await db_session.commit()

    rows = await compute_leaderboard(db_session)

    assert [r.display_name for r in rows] == ["Bob", "Alice"]  # Bob's 100 > Alice's 70
    bob_row, alice_row = rows
    assert bob_row.total_points == 100.0
    assert bob_row.tournaments_played == 1
    assert bob_row.balance == 80.0
    assert alice_row.total_points == 70.0
    assert alice_row.tournaments_played == 2
    assert alice_row.balance == 150.0


async def test_compute_leaderboard_scoped_to_one_tournament(db_session) -> None:
    """Regression guard for the exact bug this replaced: a user's leaderboard total must be the
    LIVE sum of their SETTLED predictions, matching what /auth/me/predictions would sum
    client-side -- never a separately-maintained figure that can drift from it."""
    t1 = await _make_tournament(db_session, "Cup One")
    t2 = await _make_tournament(db_session, "Cup Two")
    m1 = await _make_market(db_session, t1)
    m2 = await _make_market(db_session, t2)
    alice = await _make_user(db_session, "alice@x.com", "Alice")
    await db_session.commit()

    db_session.add_all(
        [
            _settled_prediction(m1, alice, stake=50.0, points_awarded=100.0),  # +50, in t1
            _settled_prediction(m2, alice, stake=30.0, points_awarded=50.0),  # +20, in t2 only
        ]
    )
    await db_session.commit()

    scoped_to_t1 = await compute_leaderboard(db_session, tournament_id=t1.id)
    assert len(scoped_to_t1) == 1
    assert scoped_to_t1[0].total_points == 50.0
    assert scoped_to_t1[0].tournaments_played == 1


async def test_compute_leaderboard_excludes_users_with_no_settled_history(db_session) -> None:
    await _make_user(db_session, "never_bet@x.com", "Never Bet")
    await db_session.commit()

    assert await compute_leaderboard(db_session) == []


async def test_compute_leaderboard_ignores_still_open_predictions(db_session) -> None:
    """An OPEN prediction's stake is deducted from balance but isn't a realized result yet --
    it must not count toward net profit until it's actually settled."""
    tournament = await _make_tournament(db_session, "Cup")
    market = await _make_market(db_session, tournament)
    user = await _make_user(db_session, "user@x.com", "User")
    await db_session.commit()

    db_session.add(
        Prediction(
            bet_market_id=market.id, user_id=user.id, entity_key="__market__",
            payload={"team_id": 1}, locked_at=NOW, stake_amount=50.0, odds=2.0,
            status=PredictionStatus.OPEN, points_awarded=None,
        )
    )
    await db_session.commit()

    assert await compute_leaderboard(db_session) == []


async def test_compute_leaderboard_ties_break_by_display_name(db_session) -> None:
    tournament = await _make_tournament(db_session, "Cup")
    market = await _make_market(db_session, tournament)
    zed = await _make_user(db_session, "zed@x.com", "Zed")
    amy = await _make_user(db_session, "amy@x.com", "Amy")
    await db_session.commit()

    db_session.add_all(
        [
            _settled_prediction(market, zed, stake=10.0, points_awarded=20.0),  # +10
            _settled_prediction(market, amy, stake=10.0, points_awarded=20.0),  # +10
        ]
    )
    await db_session.commit()

    rows = await compute_leaderboard(db_session)

    assert [r.display_name for r in rows] == ["Amy", "Zed"]
