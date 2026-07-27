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
    _entity_key,
    auto_close_pretournament_markets,
    settle_market,
    validate_market_creation,
)

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _prediction(
    bet_type: BetType, *, market_id: int, user_id: int, payload: dict, **kwargs
) -> Prediction:
    """Builds a Prediction the way place_prediction would -- entity_key computed the same way
    -- for tests that construct rows directly (bypassing the service) to exercise settlement in
    isolation."""
    kwargs.setdefault("locked_at", NOW)
    kwargs.setdefault("stake_amount", 10.0)
    kwargs.setdefault("odds", 2.0)
    return Prediction(
        bet_market_id=market_id,
        user_id=user_id,
        entity_key=_entity_key(bet_type, payload),
        payload=payload,
        **kwargs,
    )


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
        _prediction(
            BetType.CHAMPION,
            market_id=market.id,
            user_id=alice.id,
            payload={"team_id": team.id},
            stake_amount=100.0,
            odds=2.0,
        )
    )
    db_session.add(
        _prediction(
            BetType.CHAMPION,
            market_id=market.id,
            user_id=bob.id,
            payload={"team_id": 999},
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
        _prediction(
            BetType.TOP_N_BREAK,
            market_id=market.id,
            user_id=alice.id,
            payload={"team_ids": [team_1.id, team_2.id]},
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
        _prediction(
            BetType.HEAD_TO_HEAD,
            market_id=market.id,
            user_id=alice.id,
            payload={
                "team_a_id": team_a.id,
                "team_b_id": team_b.id,
                "predicted_winner_id": team_a.id,
            },
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
        _prediction(
            BetType.BREAKOUT_TEAM,
            market_id=market.id,
            user_id=alice.id,
            payload={"team_id": team.id},
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
        _prediction(
            BetType.ROUND_FULL_CALL,
            market_id=market.id,
            user_id=alice.id,
            payload={"debate_id": debate.id, "team_ids": exact_order},
            odds=8.0,
        )
    )
    db_session.add(
        _prediction(
            BetType.ROUND_FULL_CALL,
            market_id=market.id,
            user_id=bob.id,
            payload={"debate_id": debate.id, "team_ids": wrong_order},
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
        _prediction(
            BetType.TOP_SPEAKER_POSITION,
            market_id=market.id,
            user_id=alice.id,
            payload={"speaker_id": speakers[1].id, "position": 2},
            odds=6.0,
        )
    )
    db_session.add(
        _prediction(
            BetType.TOP_SPEAKER_POSITION,
            market_id=market.id,
            user_id=bob.id,
            # Right speaker, wrong slot -- speaker 2 actually finishes 2nd, not 1st.
            payload={"speaker_id": speakers[1].id, "position": 1},
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
        _prediction(
            BetType.TEAM_BREAK,
            market_id=market.id,
            user_id=alice.id,
            payload={"team_id": team_1.id},
        )
    )
    db_session.add(
        _prediction(
            BetType.TEAM_BREAK,
            market_id=market.id,
            user_id=bob.id,
            payload={"team_id": team_3.id},  # never breaks
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


# --- place_prediction: one open bet per entity, not per market ---------------------------


async def _make_round_with_two_debates(db_session, tournament):
    round_1 = Round(
        tournament_id=tournament.id, seq=1, name="Round 1", stage=RoundStage.PRELIMINARY,
        status=RoundStatus.RELEASED,
    )
    db_session.add(round_1)
    await db_session.flush()
    teams = [
        Team(tournament_id=tournament.id, external_id=i, name=f"Team {i}") for i in range(1, 5)
    ]
    db_session.add_all(teams)
    await db_session.flush()
    debate_a = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    debate_b = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=2)
    db_session.add_all([debate_a, debate_b])
    await db_session.flush()
    for debate, pair in ((debate_a, teams[:2]), (debate_b, teams[2:])):
        for team, position in zip(
            pair, (BPPosition.OPENING_GOVERNMENT, BPPosition.OPENING_OPPOSITION), strict=True
        ):
            db_session.add(DebateTeam(debate_id=debate.id, team_id=team.id, position=position))
    await db_session.flush()
    return round_1, debate_a, debate_b, teams


async def test_place_prediction_allows_one_bet_per_debate_in_a_round_market(db_session) -> None:
    from app.services.betting_service import place_prediction

    tournament = await _make_tournament(db_session)
    round_1, debate_a, debate_b, teams = await _make_round_with_two_debates(db_session, tournament)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=round_1.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    await db_session.commit()

    await place_prediction(
        db_session, market, alice, {"debate_id": debate_a.id, "team_id": teams[0].id}, 10.0
    )
    await db_session.commit()
    await place_prediction(
        db_session, market, alice, {"debate_id": debate_b.id, "team_id": teams[2].id}, 10.0
    )
    await db_session.commit()

    predictions = (
        (
            await db_session.execute(
                select(Prediction).where(
                    Prediction.bet_market_id == market.id, Prediction.user_id == alice.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(predictions) == 2  # one sala bet per debate -- NOT collapsed into one
    assert {p.entity_key for p in predictions} == {f"debate:{debate_a.id}", f"debate:{debate_b.id}"}


async def test_place_prediction_same_debate_replaces_not_duplicates(db_session) -> None:
    from app.services.betting_service import place_prediction

    tournament = await _make_tournament(db_session)
    round_1, debate_a, _debate_b, teams = await _make_round_with_two_debates(db_session, tournament)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=round_1.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    await db_session.commit()
    balance_before = alice.balance

    await place_prediction(
        db_session, market, alice, {"debate_id": debate_a.id, "team_id": teams[0].id}, 10.0
    )
    await db_session.commit()
    # Same debate, different pick and stake -- must REPLACE, not create a second row, and must
    # refund the first stake before charging the new one (no double-charge).
    await place_prediction(
        db_session, market, alice, {"debate_id": debate_a.id, "team_id": teams[1].id}, 25.0
    )
    await db_session.commit()

    predictions = (
        (
            await db_session.execute(
                select(Prediction).where(
                    Prediction.bet_market_id == market.id, Prediction.user_id == alice.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(predictions) == 1
    assert predictions[0].payload == {"debate_id": debate_a.id, "team_id": teams[1].id}
    assert predictions[0].stake_amount == 25.0
    await db_session.refresh(alice)
    assert alice.balance == balance_before - 25.0


async def test_place_prediction_speaker_positions_are_independent_slots(db_session) -> None:
    from app.services.betting_service import place_prediction

    tournament = await _make_tournament(db_session)
    team = Team(tournament_id=tournament.id, external_id=1, name="Team A")
    db_session.add(team)
    await db_session.flush()
    speakers = [
        Speaker(tournament_id=tournament.id, team_id=team.id, name=f"Speaker {i}")
        for i in range(1, 3)
    ]
    db_session.add_all(speakers)
    await db_session.flush()
    market = await _make_market(db_session, tournament, BetType.TOP_SPEAKER_POSITION)
    alice = await _make_user(db_session, "alice@example.com")
    await db_session.commit()

    # Position 1 -> speaker A, position 2 -> speaker B: two INDEPENDENT open predictions.
    await place_prediction(
        db_session, market, alice, {"speaker_id": speakers[0].id, "position": 1}, 5.0
    )
    await db_session.commit()
    await place_prediction(
        db_session, market, alice, {"speaker_id": speakers[1].id, "position": 2}, 5.0
    )
    await db_session.commit()

    predictions = (
        (
            await db_session.execute(
                select(Prediction).where(
                    Prediction.bet_market_id == market.id, Prediction.user_id == alice.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(predictions) == 2
    assert {p.entity_key for p in predictions} == {"position:1", "position:2"}

    # Re-picking position 1 with a DIFFERENT speaker replaces that slot's bet, not a new row.
    await place_prediction(
        db_session, market, alice, {"speaker_id": speakers[1].id, "position": 1}, 8.0
    )
    await db_session.commit()
    predictions_after = (
        (
            await db_session.execute(
                select(Prediction).where(
                    Prediction.bet_market_id == market.id, Prediction.user_id == alice.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(predictions_after) == 2
    by_key = {p.entity_key: p for p in predictions_after}
    assert by_key["position:1"].payload["speaker_id"] == speakers[1].id
    assert by_key["position:1"].stake_amount == 8.0


async def _make_round_market_with_one_resolved_debate(db_session):
    """A round_winner market over two debates where only debate A has a published result --
    the exact mid-round state a scrape cycle sees while the rest of the round is still being
    judged."""
    tournament = await _make_tournament(db_session)
    round_1, debate_a, debate_b, teams = await _make_round_with_two_debates(db_session, tournament)
    # Debate A's ballot is in; debate B's is not.
    debate_a_teams = (
        (
            await db_session.execute(
                select(DebateTeam).where(DebateTeam.debate_id == debate_a.id)
            )
        )
        .scalars()
        .all()
    )
    for rank, debate_team in enumerate(debate_a_teams, start=1):
        debate_team.rank_in_debate = rank
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=round_1.id
    )
    return market, debate_a, debate_b, teams, debate_a_teams


async def test_settle_market_never_re_credits_an_already_settled_prediction(db_session) -> None:
    """Regression: a per-prediction market stays un-SETTLED while any of its debates is still
    unresolved, so every later scrape cycle revisits it. Re-scoring the predictions that already
    resolved would credit their payout again on each cycle, minting balance from nothing."""
    market, debate_a, debate_b, teams, debate_a_teams = (
        await _make_round_market_with_one_resolved_debate(db_session)
    )
    winner_team_id = debate_a_teams[0].team_id

    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    alice.balance = 0.0
    db_session.add_all(
        [
            _prediction(
                BetType.ROUND_WINNER,
                market_id=market.id,
                user_id=alice.id,
                payload={"debate_id": debate_a.id, "team_id": winner_team_id},
            ),
            # Bob's debate has no result yet, so the market can't finish settling.
            _prediction(
                BetType.ROUND_WINNER,
                market_id=market.id,
                user_id=bob.id,
                payload={"debate_id": debate_b.id, "team_id": teams[2].id},
            ),
        ]
    )
    await db_session.commit()

    assert await settle_market(db_session, market) is False
    await db_session.commit()
    balance_after_first_cycle = alice.balance
    assert balance_after_first_cycle == 20.0  # stake 10.0 * odds 2.0

    # Two more scrape cycles while debate B is still pending.
    for _ in range(2):
        assert await settle_market(db_session, market) is False
        await db_session.commit()

    assert alice.balance == balance_after_first_cycle
    assert market.status != BetMarketStatus.SETTLED


async def test_settle_market_leaves_an_open_market_with_no_bets_alone(db_session) -> None:
    """Regression: `all([])` is vacuously true, so an OPEN round market nobody has bet on yet
    must not be swept into SETTLED by the next scrape cycle before anyone can play it."""
    market, _debate_a, _debate_b, _teams, _dt = (
        await _make_round_market_with_one_resolved_debate(db_session)
    )
    await db_session.commit()
    assert market.status == BetMarketStatus.OPEN

    assert await settle_market(db_session, market) is False
    await db_session.commit()

    assert market.status == BetMarketStatus.OPEN
