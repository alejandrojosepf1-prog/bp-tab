import datetime

import pytest
from sqlalchemy import select

from app.models import (
    Break,
    BreakCategory,
    Debate,
    DebateTeam,
    LeaderboardEntry,
    Round,
    Speaker,
    SpeakerScore,
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
    SpeakerRole,
    TournamentStatus,
    UserRole,
)
from app.services.betting_service import (
    MarketCreationError,
    auto_close_pretournament_markets,
    settle_market,
    validate_market_creation,
)

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


async def _make_tournament(db_session, **kwargs) -> Tournament:
    kwargs.setdefault("status", TournamentStatus.IN_PROGRESS)
    tournament = Tournament(
        name="Test Cup",
        slug="test-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
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
            bet_market_id=market.id,
            user_id=alice.id,
            payload={"team_id": team.id},
            locked_at=NOW,
            stake_amount=100.0,
            odds=2.0,
        )
    )
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=bob.id,
            payload={"team_id": 999},
            locked_at=NOW,
            stake_amount=50.0,
            odds=3.0,
        )
    )
    await db_session.commit()
    alice_balance_before = alice.balance

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    assert market.status == BetMarketStatus.SETTLED

    predictions = (
        (await db_session.execute(select(Prediction).order_by(Prediction.user_id))).scalars().all()
    )
    by_user = {p.user_id: p for p in predictions}
    # Alice won: payout = stake * odds = 100 * 2.0.
    assert by_user[alice.id].points_awarded == 200.0
    assert by_user[alice.id].status == PredictionStatus.SETTLED
    # Bob lost: stake was already deducted at placement time, no further loss on settlement.
    assert by_user[bob.id].points_awarded == 0.0

    await db_session.refresh(alice)
    assert alice.balance == alice_balance_before + 200.0

    leaderboard = (await db_session.execute(select(LeaderboardEntry))).scalars().all()
    by_user_lb = {entry.user_id: entry for entry in leaderboard}
    # total_points is net profit (payout - stake) for THIS tournament, not the global balance.
    assert by_user_lb[alice.id].total_points == 100.0  # 200 payout - 100 stake
    assert by_user_lb[alice.id].rank == 1
    assert by_user_lb[bob.id].total_points == -50.0  # 0 payout - 50 stake
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
            stake_amount=10.0,
            odds=5.0,
        )
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    prediction = (await db_session.execute(select(Prediction))).scalar_one()
    # Exact-order top-N match (all-or-nothing parlay, see domain.bet_outcomes): stake * odds.
    assert prediction.points_awarded == 50.0


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
            stake_amount=10.0,
            odds=4.0,
        )
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    prediction = (await db_session.execute(select(Prediction))).scalar_one()
    assert prediction.points_awarded == 40.0


async def test_settle_market_breakout_team_requires_manual_outcome(db_session) -> None:
    tournament = await _make_tournament(db_session)
    team = Team(tournament_id=tournament.id, external_id=1, name="Cinderella")
    db_session.add(team)
    await db_session.flush()
    market = await _make_market(db_session, tournament, BetType.BREAKOUT_TEAM)
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=alice.id,
            payload={"team_id": team.id},
            locked_at=NOW,
            stake_amount=10.0,
            odds=4.0,
        )
    )
    await db_session.commit()

    not_yet = await settle_market(db_session, market)
    assert not_yet is False

    settled = await settle_market(db_session, market, manual_outcome={"breakout_team_id": team.id})
    await db_session.commit()
    assert settled is True
    assert market.status == BetMarketStatus.SETTLED


async def test_settle_market_round_full_call_exact_order_wins(db_session) -> None:
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
    teams = [
        Team(tournament_id=tournament.id, external_id=i, name=f"Team {i}") for i in range(1, 5)
    ]
    db_session.add_all(teams)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    positions = [
        BPPosition.OPENING_GOVERNMENT,
        BPPosition.OPENING_OPPOSITION,
        BPPosition.CLOSING_GOVERNMENT,
        BPPosition.CLOSING_OPPOSITION,
    ]
    # Team 3 finishes 1st, Team 1 2nd, Team 4 3rd, Team 2 4th.
    ranks_by_team = {teams[2].id: 1, teams[0].id: 2, teams[3].id: 3, teams[1].id: 4}
    for team, position in zip(teams, positions, strict=True):
        db_session.add(
            DebateTeam(
                debate_id=debate.id,
                team_id=team.id,
                position=position,
                rank_in_debate=ranks_by_team[team.id],
            )
        )
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.ROUND_FULL_CALL, target_round_id=round_1.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    exact_order = [teams[2].id, teams[0].id, teams[3].id, teams[1].id]
    wrong_order = [teams[0].id, teams[2].id, teams[3].id, teams[1].id]
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=alice.id,
            payload={"debate_id": debate.id, "team_ids": exact_order},
            locked_at=NOW,
            stake_amount=10.0,
            odds=8.0,
        )
    )
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=bob.id,
            payload={"debate_id": debate.id, "team_ids": wrong_order},
            locked_at=NOW,
            stake_amount=10.0,
            odds=8.0,
        )
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    predictions = {
        p.user_id: p
        for p in (await db_session.execute(select(Prediction))).scalars().all()
    }
    assert predictions[alice.id].points_awarded == 80.0
    assert predictions[bob.id].points_awarded == 0.0


async def test_settle_market_top_speaker_position(db_session) -> None:
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
    team = Team(tournament_id=tournament.id, external_id=1, name="Team A")
    db_session.add(team)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    debate_team = DebateTeam(
        debate_id=debate.id,
        team_id=team.id,
        position=BPPosition.OPENING_GOVERNMENT,
        rank_in_debate=1,
    )
    db_session.add(debate_team)
    await db_session.flush()

    speakers = [
        Speaker(tournament_id=tournament.id, team_id=team.id, name=f"Speaker {i}")
        for i in range(1, 4)
    ]
    db_session.add_all(speakers)
    await db_session.flush()
    # Speaker 1 tops the tab, Speaker 2 is 2nd, Speaker 3 is 3rd.
    scores = [
        (speakers[0], SpeakerRole.PM, 90.0),
        (speakers[1], SpeakerRole.DPM, 80.0),
        (speakers[2], SpeakerRole.LO, 70.0),
    ]
    for speaker, role, score in scores:
        db_session.add(
            SpeakerScore(
                debate_team_id=debate_team.id, speaker_id=speaker.id, role=role, score=score
            )
        )
    await db_session.flush()

    market = await _make_market(db_session, tournament, BetType.TOP_SPEAKER_POSITION)
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=alice.id,
            payload={"speaker_id": speakers[1].id, "position": 2},
            locked_at=NOW,
            stake_amount=10.0,
            odds=6.0,
        )
    )
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=bob.id,
            # Right speaker, wrong slot -- speaker 2 actually finishes 2nd, not 1st.
            payload={"speaker_id": speakers[1].id, "position": 1},
            locked_at=NOW,
            stake_amount=10.0,
            odds=6.0,
        )
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    predictions = {
        p.user_id: p
        for p in (await db_session.execute(select(Prediction))).scalars().all()
    }
    assert predictions[alice.id].points_awarded == 60.0
    assert predictions[bob.id].points_awarded == 0.0


async def test_settle_market_team_break_is_membership_not_exact_order(db_session) -> None:
    tournament = await _make_tournament(db_session)
    category = BreakCategory(tournament_id=tournament.id, name="Open", slug="open", break_size=2)
    db_session.add(category)
    await db_session.flush()
    team_1 = Team(tournament_id=tournament.id, external_id=1, name="Team 1")
    team_2 = Team(tournament_id=tournament.id, external_id=2, name="Team 2")
    team_3 = Team(tournament_id=tournament.id, external_id=3, name="Team 3")
    db_session.add_all([team_1, team_2, team_3])
    await db_session.flush()
    # Officially breaking teams: 1 and 2 (rank order doesn't matter for team_break).
    db_session.add(
        Break(
            tournament_id=tournament.id, break_category_id=category.id, team_id=team_1.id, rank=2
        )
    )
    db_session.add(
        Break(
            tournament_id=tournament.id, break_category_id=category.id, team_id=team_2.id, rank=1
        )
    )
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.TEAM_BREAK, target_break_category_id=category.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=alice.id,
            payload={"team_id": team_1.id},
            locked_at=NOW,
            stake_amount=10.0,
            odds=2.0,
        )
    )
    db_session.add(
        Prediction(
            bet_market_id=market.id,
            user_id=bob.id,
            payload={"team_id": team_3.id},  # never breaks
            locked_at=NOW,
            stake_amount=10.0,
            odds=2.0,
        )
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    predictions = {
        p.user_id: p
        for p in (await db_session.execute(select(Prediction))).scalars().all()
    }
    assert predictions[alice.id].points_awarded == 20.0
    assert predictions[bob.id].points_awarded == 0.0


# --- validate_market_creation / auto_close_pretournament_markets -------------------------


def test_validate_market_creation_champion_requires_upcoming_tournament() -> None:
    upcoming = Tournament(
        name="T", slug="t", source_base_url="https://x", source_slug="o",
        status=TournamentStatus.UPCOMING,
    )
    in_progress = Tournament(
        name="T", slug="t", source_base_url="https://x", source_slug="o",
        status=TournamentStatus.IN_PROGRESS,
    )
    validate_market_creation(
        upcoming, BetType.CHAMPION, target_round_id=None, target_break_category_id=None
    )  # does not raise
    with pytest.raises(MarketCreationError):
        validate_market_creation(
            in_progress, BetType.CHAMPION, target_round_id=None, target_break_category_id=None
        )


def test_validate_market_creation_round_scoped_types_require_target_round_id() -> None:
    tournament = Tournament(
        name="T", slug="t", source_base_url="https://x", source_slug="o",
        status=TournamentStatus.IN_PROGRESS,
    )
    for bet_type in (BetType.ROUND_WINNER, BetType.ROUND_FULL_CALL):
        with pytest.raises(MarketCreationError):
            validate_market_creation(
                tournament, bet_type, target_round_id=None, target_break_category_id=None
            )
        validate_market_creation(
            tournament, bet_type, target_round_id=1, target_break_category_id=None
        )  # does not raise


def test_validate_market_creation_team_break_requires_target_break_category_id() -> None:
    tournament = Tournament(
        name="T", slug="t", source_base_url="https://x", source_slug="o",
        status=TournamentStatus.IN_PROGRESS,
    )
    with pytest.raises(MarketCreationError):
        validate_market_creation(
            tournament, BetType.TEAM_BREAK, target_round_id=None, target_break_category_id=None
        )
    validate_market_creation(
        tournament, BetType.TEAM_BREAK, target_round_id=None, target_break_category_id=1
    )  # does not raise


def test_validate_market_creation_rejects_retired_bet_types() -> None:
    tournament = Tournament(
        name="T", slug="t", source_base_url="https://x", source_slug="o",
        status=TournamentStatus.UPCOMING,
    )
    with pytest.raises(MarketCreationError):
        validate_market_creation(
            tournament, BetType.HEAD_TO_HEAD, target_round_id=None, target_break_category_id=None
        )


async def test_auto_close_pretournament_markets_closes_open_champion_once_started(
    db_session,
) -> None:
    tournament = await _make_tournament(db_session, status=TournamentStatus.UPCOMING)
    market = await _make_market(db_session, tournament, BetType.CHAMPION)
    await db_session.commit()

    # Still upcoming: nothing to close.
    closed_count = await auto_close_pretournament_markets(db_session, tournament)
    assert closed_count == 0
    await db_session.refresh(market)
    assert market.status == BetMarketStatus.OPEN

    tournament.status = TournamentStatus.IN_PROGRESS
    await db_session.flush()
    closed_count = await auto_close_pretournament_markets(db_session, tournament)
    await db_session.commit()
    assert closed_count == 1
    await db_session.refresh(market)
    assert market.status == BetMarketStatus.CLOSED

    # Idempotent: nothing left open to close on a second call.
    assert await auto_close_pretournament_markets(db_session, tournament) == 0
