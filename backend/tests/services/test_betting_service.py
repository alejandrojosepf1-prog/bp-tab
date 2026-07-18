import datetime

from sqlalchemy import select

from app.models import (
    Break,
    BreakCategory,
    Debate,
    DebateTeam,
    LeaderboardEntry,
    Round,
    Team,
    Tournament,
    User,
)
from app.models.betting import BetMarket, Prediction
from app.models.enums import (
    BetMarketStatus,
    BetType,
    BPPosition,
    BreakStatus,
    PredictionStatus,
    RoundStage,
    RoundStatus,
    TournamentStatus,
    UserRole,
)
from app.services.betting_service import settle_market

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


async def _make_tournament(db_session, **kwargs) -> Tournament:
    tournament = Tournament(
        name="Test Cup",
        slug="test-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
        **kwargs,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _make_user(db_session, email: str) -> User:
    user = User(email=email, password_hash="x", display_name=email, role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_market(
    db_session, tournament: Tournament, bet_type: BetType, **kwargs
) -> BetMarket:
    market = BetMarket(
        tournament_id=tournament.id,
        bet_type=bet_type,
        label="test market",
        opens_at=NOW,
        closes_at=NOW,
        points_rule={},
        **kwargs,
    )
    db_session.add(market)
    await db_session.flush()
    return market


async def test_settle_market_champion_scores_and_updates_leaderboard(db_session) -> None:
    tournament = await _make_tournament(db_session)
    team = Team(tournament_id=tournament.id, external_id=1, name="Winners")
    db_session.add(team)
    await db_session.flush()
    tournament.champion_team_id = team.id
    await db_session.flush()

    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    db_session.add(
        Prediction(
            bet_market_id=market.id, user_id=alice.id, payload={"team_id": team.id}, locked_at=NOW
        )
    )
    db_session.add(
        Prediction(bet_market_id=market.id, user_id=bob.id, payload={"team_id": 999}, locked_at=NOW)
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    assert market.status == BetMarketStatus.SETTLED

    predictions = (
        (await db_session.execute(select(Prediction).order_by(Prediction.user_id))).scalars().all()
    )
    by_user = {p.user_id: p for p in predictions}
    assert by_user[alice.id].points_awarded == 100.0
    assert by_user[alice.id].status == PredictionStatus.SETTLED
    assert by_user[bob.id].points_awarded == 0.0

    leaderboard = (await db_session.execute(select(LeaderboardEntry))).scalars().all()
    by_user_lb = {entry.user_id: entry for entry in leaderboard}
    assert by_user_lb[alice.id].total_points == 100.0
    assert by_user_lb[alice.id].rank == 1
    assert by_user_lb[bob.id].total_points == 0.0
    assert by_user_lb[bob.id].rank == 2


async def test_settle_market_returns_false_when_not_yet_resolvable(db_session) -> None:
    tournament = await _make_tournament(db_session)  # champion_team_id still None
    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    await db_session.commit()

    settled = await settle_market(db_session, market)
    assert settled is False
    assert market.status == BetMarketStatus.OPEN


async def test_settle_market_top_n_break(db_session) -> None:
    tournament = await _make_tournament(db_session)
    category = BreakCategory(tournament_id=tournament.id, name="Open", slug="open", break_size=2)
    db_session.add(category)
    await db_session.flush()
    team_1 = Team(tournament_id=tournament.id, external_id=1, name="Team 1")
    team_2 = Team(tournament_id=tournament.id, external_id=2, name="Team 2")
    db_session.add_all([team_1, team_2])
    await db_session.flush()
    db_session.add(
        Break(
            tournament_id=tournament.id,
            break_category_id=category.id,
            team_id=team_1.id,
            rank=1,
            status=BreakStatus.CONFIRMED,
        )
    )
    db_session.add(
        Break(
            tournament_id=tournament.id,
            break_category_id=category.id,
            team_id=team_2.id,
            rank=2,
            status=BreakStatus.CONFIRMED,
        )
    )
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.TOP_N_BREAK, target_break_category_id=category.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=alice.id,
            payload={"team_ids": [team_1.id, team_2.id]},
            locked_at=NOW,
        )
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    prediction = (await db_session.execute(select(Prediction))).scalar_one()
    assert prediction.points_awarded == 30.0  # 2 exact-position hits: (10+5) * 2


async def test_settle_market_head_to_head_is_per_prediction(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(round_1)
    await db_session.flush()
    team_a = Team(tournament_id=tournament.id, external_id=1, name="Team A")
    team_b = Team(tournament_id=tournament.id, external_id=2, name="Team B")
    db_session.add_all([team_a, team_b])
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    db_session.add(
        DebateTeam(
            debate_id=debate.id,
            team_id=team_a.id,
            position=BPPosition.OPENING_GOVERNMENT,
            rank_in_debate=1,
        )
    )
    db_session.add(
        DebateTeam(
            debate_id=debate.id,
            team_id=team_b.id,
            position=BPPosition.OPENING_OPPOSITION,
            rank_in_debate=2,
        )
    )
    await db_session.flush()

    market = await _make_market(db_session, tournament, BetType.HEAD_TO_HEAD)
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=alice.id,
            payload={
                "team_a_id": team_a.id,
                "team_b_id": team_b.id,
                "predicted_winner_id": team_a.id,
            },
            locked_at=NOW,
        )
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    prediction = (await db_session.execute(select(Prediction))).scalar_one()
    assert prediction.points_awarded == 15.0


async def test_settle_market_breakout_team_requires_manual_outcome(db_session) -> None:
    tournament = await _make_tournament(db_session)
    team = Team(tournament_id=tournament.id, external_id=1, name="Cinderella")
    db_session.add(team)
    await db_session.flush()
    market = await _make_market(db_session, tournament, BetType.BREAKOUT_TEAM)
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add(
        Prediction(
            bet_market_id=market.id, user_id=alice.id, payload={"team_id": team.id}, locked_at=NOW
        )
    )
    await db_session.commit()

    not_yet = await settle_market(db_session, market)
    assert not_yet is False

    settled = await settle_market(db_session, market, manual_outcome={"breakout_team_id": team.id})
    await db_session.commit()
    assert settled is True
    assert market.status == BetMarketStatus.SETTLED
