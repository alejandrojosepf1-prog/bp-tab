import datetime
import itertools

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
    DebateStatus,
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
    settle_pending_sub_bets,
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
    # Pieza 3: payout is the FINAL pari-mutuel split (settlement_payout_ratio), not the frozen
    # `odds` locked in at bet time -- Alice's own `odds=2.0` above is now just a historical
    # placement-time projection, never read at settlement. Only one real team exists (Bob's
    # pick, team_id=999, isn't a registered team), so its prior is 1.0; blended against the
    # pool (100 on the champion, 150 total) with the default seed of 200:
    #   p = (100 + 200*1.0) / (150 + 200) = 300/350 = 0.857142... -> odds = round(1/p, 2) = 1.17
    assert by_user[alice.id].points_awarded == 117.0
    assert by_user[alice.id].status == PredictionStatus.SETTLED
    # Bob lost: stake was already deducted at placement time, no further loss on settlement.
    assert by_user[bob.id].points_awarded == 0.0

    await db_session.refresh(alice)
    assert alice.balance == alice_balance_before + 117.0

    leaderboard = (await db_session.execute(select(LeaderboardEntry))).scalars().all()
    by_user_lb = {entry.user_id: entry for entry in leaderboard}
    # total_points is net profit (payout - stake) for THIS tournament, not the global balance.
    assert by_user_lb[alice.id].total_points == 17.0  # 117 payout - 100 stake
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
    # Pieza 3: payout is the pari-mutuel split of the debate's final pool (Alice's exact_order
    # vs. Bob's wrong_order, 10 staked each), priced from team power that now includes THIS
    # debate's own just-judged result (settlement always reads current standings) -- not a hand
    # round number like the old frozen odds=8.0. Alice's `odds` field is only the placement-time
    # projection now; it's never read at settlement.
    assert predictions[alice.id].points_awarded == pytest.approx(36.5)
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
    # Pieza 3: pari-mutuel payout from the position's own compartment (see
    # settlement_payout_ratio's TOP_SPEAKER_POSITION branch / speaker_position_prior), not the
    # frozen odds=6.0 above.
    assert predictions[alice.id].points_awarded == pytest.approx(31.3)
    assert predictions[bob.id].points_awarded == 0.0


async def test_top_speaker_position_does_not_settle_until_every_preliminary_round_is_judged(
    db_session,
) -> None:
    """Regression: speaker points only ever come from preliminary rounds, so the ranking is
    only truly final once EVERY preliminary round is judged -- not as soon as any 3 speakers
    happen to have a score, which used to let this settle as early as Round 1 and then never
    revisit it (settlement is one-way)."""
    tournament = await _make_tournament(db_session)
    round_1 = Round(
        tournament_id=tournament.id, seq=1, name="Round 1",
        stage=RoundStage.PRELIMINARY, status=RoundStatus.COMPLETED,
    )
    # Round 2 EXISTS (the results nav lists every preliminary round from the start, played or
    # not -- see ScrapedRoundRef) but hasn't been judged yet.
    round_2 = Round(
        tournament_id=tournament.id, seq=2, name="Round 2",
        stage=RoundStage.PRELIMINARY, status=RoundStatus.RELEASED,
    )
    db_session.add_all([round_1, round_2])
    await db_session.flush()
    team = Team(tournament_id=tournament.id, external_id=1, name="Team A")
    db_session.add(team)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    debate_team = DebateTeam(
        debate_id=debate.id, team_id=team.id,
        position=BPPosition.OPENING_GOVERNMENT, rank_in_debate=1,
    )
    db_session.add(debate_team)
    await db_session.flush()
    speakers = [
        Speaker(tournament_id=tournament.id, team_id=team.id, name=f"Speaker {i}")
        for i in range(1, 4)
    ]
    db_session.add_all(speakers)
    await db_session.flush()
    for speaker, role, score in [
        (speakers[0], SpeakerRole.PM, 90.0),
        (speakers[1], SpeakerRole.DPM, 80.0),
        (speakers[2], SpeakerRole.LO, 70.0),
    ]:
        db_session.add(
            SpeakerScore(
                debate_team_id=debate_team.id, speaker_id=speaker.id, role=role, score=score
            )
        )
    await db_session.commit()

    market = await _make_market(db_session, tournament, BetType.TOP_SPEAKER_POSITION)
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is False
    await db_session.refresh(market)
    assert market.status != BetMarketStatus.SETTLED


async def test_top_speaker_position_settles_positions_past_3_once_ranking_is_final(
    db_session,
) -> None:
    """The 'Tabla de oradores' market now goes to 10 slots, not 3 -- confirm a position-5 pick
    settles correctly once every preliminary round is judged."""
    tournament = await _make_tournament(db_session)
    round_1 = Round(
        tournament_id=tournament.id, seq=1, name="Round 1",
        stage=RoundStage.PRELIMINARY, status=RoundStatus.COMPLETED,
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
        debate_id=debate.id, team_id=team.id,
        position=BPPosition.OPENING_GOVERNMENT, rank_in_debate=1,
    )
    db_session.add(debate_team)
    await db_session.flush()
    # 6 speakers, strictly descending scores -- speakers[4] (score 50) is exactly 5th.
    speakers = [
        Speaker(tournament_id=tournament.id, team_id=team.id, name=f"Speaker {i}")
        for i in range(1, 7)
    ]
    db_session.add_all(speakers)
    await db_session.flush()
    roles = [
        SpeakerRole.PM, SpeakerRole.DPM, SpeakerRole.LO,
        SpeakerRole.DLO, SpeakerRole.MG, SpeakerRole.GW,
    ]
    for speaker, role, score in zip(speakers, roles, [90.0, 80.0, 70.0, 60.0, 50.0, 40.0], strict=True):
        db_session.add(
            SpeakerScore(
                debate_team_id=debate_team.id, speaker_id=speaker.id, role=role, score=score
            )
        )
    await db_session.commit()

    market = await _make_market(db_session, tournament, BetType.TOP_SPEAKER_POSITION)
    alice = await _make_user(db_session, "alice-deep@example.com")
    bob = await _make_user(db_session, "bob-deep@example.com")
    db_session.add(
        _prediction(
            BetType.TOP_SPEAKER_POSITION, market_id=market.id, user_id=alice.id,
            payload={"speaker_id": speakers[4].id, "position": 5}, odds=8.0,
        )
    )
    db_session.add(
        _prediction(
            BetType.TOP_SPEAKER_POSITION, market_id=market.id, user_id=bob.id,
            payload={"speaker_id": speakers[5].id, "position": 5}, odds=8.0,
        )
    )
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    assert settled is True
    predictions = {
        p.user_id: p for p in (await db_session.execute(select(Prediction))).scalars().all()
    }
    # Pieza 3: pari-mutuel payout, not 10.0 stake * frozen odds=8.0.
    assert predictions[alice.id].points_awarded == pytest.approx(47.2)
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
    assert {p.entity_key for p in predictions} == {
        f"debate:{debate_a.id}:team:{teams[0].id}",
        f"debate:{debate_b.id}:team:{teams[2].id}",
    }


async def test_place_prediction_same_team_same_debate_replaces_not_duplicates(db_session) -> None:
    """Re-submitting the SAME team in the same debate is an edit (one entity_key), unlike
    picking a DIFFERENT team in that debate, which is a second independent pick -- see
    `test_round_winner_allows_up_to_two_independent_single_team_picks_per_room`."""
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
    # Same debate, SAME team, different stake -- must REPLACE, not create a second row, and must
    # refund the first stake before charging the new one (no double-charge).
    await place_prediction(
        db_session, market, alice, {"debate_id": debate_a.id, "team_id": teams[0].id}, 25.0
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
    assert predictions[0].payload == {"debate_id": debate_a.id, "team_id": teams[0].id}
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
    # Pieza 3: pari-mutuel payout, not stake * frozen odds -- the exact number doesn't matter
    # for what this regression actually guards (that repeated cycles never pay it AGAIN, checked
    # below), only that it's stable across cycles.
    assert balance_after_first_cycle == pytest.approx(15.4)

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


def test_set_bet_market_status_reopen_requires_future_closes_at_if_expired() -> None:
    from app.services.betting_service import set_bet_market_status

    past = NOW - datetime.timedelta(hours=1)
    market = BetMarket(
        tournament_id=1, bet_type=BetType.CHAMPION, label="m",
        opens_at=past, closes_at=past, points_rule={}, status=BetMarketStatus.CLOSED,
    )
    with pytest.raises(ValueError, match="reopening"):
        set_bet_market_status(market, BetMarketStatus.OPEN)
    assert market.status == BetMarketStatus.CLOSED  # unchanged


def test_set_bet_market_status_reopen_succeeds_with_new_future_closes_at() -> None:
    from app.services.betting_service import set_bet_market_status

    past = NOW - datetime.timedelta(hours=1)
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    market = BetMarket(
        tournament_id=1, bet_type=BetType.CHAMPION, label="m",
        opens_at=past, closes_at=past, points_rule={}, status=BetMarketStatus.CLOSED,
    )
    set_bet_market_status(market, BetMarketStatus.OPEN, new_closes_at=future)
    assert market.status == BetMarketStatus.OPEN
    assert market.closes_at == future


def test_set_bet_market_status_reopen_ok_without_new_closes_at_if_still_future() -> None:
    from app.services.betting_service import set_bet_market_status

    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    market = BetMarket(
        tournament_id=1, bet_type=BetType.CHAMPION, label="m",
        opens_at=NOW, closes_at=future, points_rule={}, status=BetMarketStatus.CLOSED,
    )
    set_bet_market_status(market, BetMarketStatus.OPEN)
    assert market.status == BetMarketStatus.OPEN


def test_set_bet_market_status_rejects_a_new_closes_at_in_the_past() -> None:
    from app.services.betting_service import set_bet_market_status

    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    market = BetMarket(
        tournament_id=1, bet_type=BetType.CHAMPION, label="m",
        opens_at=NOW, closes_at=future, points_rule={}, status=BetMarketStatus.OPEN,
    )
    with pytest.raises(ValueError, match="future"):
        set_bet_market_status(market, BetMarketStatus.OPEN, new_closes_at=NOW)


async def test_round_winner_settles_via_manual_advancing_teams_in_elimination(db_session) -> None:
    """Regression: an elimination debate resolved via manual_results_service.
    apply_manual_advancing_teams (the path used when Tabbycat never confirms an out-round
    ballot, e.g. a Grand Final everyone in the room already knows the result of) only sets
    DebateTeam.advanced, never .rank_in_debate -- a BP out-round advances 2 of 4 teams, so
    there's no single "1st place" the way there is in a preliminary round. Before this fix,
    round_winner's settlement only ever looked at rank_in_debate, so a bet on an out-round
    resolved this way could never settle at all."""
    from app.services.manual_results_service import apply_manual_advancing_teams

    tournament = await _make_tournament(db_session)
    elim_round = Round(
        tournament_id=tournament.id, seq=10, name="Quarterfinal", stage=RoundStage.ELIMINATION,
        status=RoundStatus.RELEASED,
    )
    db_session.add(elim_round)
    await db_session.flush()
    teams = [
        Team(tournament_id=tournament.id, external_id=i, name=f"QF Team {i}") for i in range(1, 5)
    ]
    db_session.add_all(teams)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=elim_round.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    for team, position in zip(
        teams,
        [
            BPPosition.OPENING_GOVERNMENT, BPPosition.OPENING_OPPOSITION,
            BPPosition.CLOSING_GOVERNMENT, BPPosition.CLOSING_OPPOSITION,
        ],
        strict=True,
    ):
        db_session.add(DebateTeam(debate_id=debate.id, team_id=team.id, position=position))
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=elim_round.id
    )
    alice = await _make_user(db_session, "alice@example.com")  # bets on an advancing team
    bob = await _make_user(db_session, "bob@example.com")  # bets on an eliminated team

    db_session.add_all(
        [
            _prediction(
                BetType.ROUND_WINNER, market_id=market.id, user_id=alice.id,
                payload={"debate_id": debate.id, "team_id": teams[0].id},
                stake_amount=10.0, odds=2.0,
            ),
            _prediction(
                BetType.ROUND_WINNER, market_id=market.id, user_id=bob.id,
                payload={"debate_id": debate.id, "team_id": teams[2].id},
                stake_amount=10.0, odds=2.0,
            ),
        ]
    )
    await db_session.commit()
    alice_balance_before = alice.balance

    # Not settleable yet -- advanced is still null for every team.
    assert await settle_market(db_session, market) is False

    # Admin marks teams 0 and 1 as the two that advance (teams[0] is Alice's pick).
    await apply_manual_advancing_teams(db_session, debate.id, [teams[0].id, teams[1].id])
    await db_session.commit()

    assert await settle_market(db_session, market) is True
    await db_session.commit()

    predictions = (
        (await db_session.execute(select(Prediction).order_by(Prediction.user_id))).scalars().all()
    )
    by_user = {p.user_id: p for p in predictions}
    assert by_user[alice.id].status == PredictionStatus.SETTLED
    # Pieza 3: pari-mutuel elimination-round payout (top-N, ELIMINATION_SEED), not stake * odds.
    assert by_user[alice.id].points_awarded == pytest.approx(25.3)
    assert by_user[bob.id].points_awarded == 0.0  # eliminated -> lost

    await db_session.refresh(alice)
    assert alice.balance == pytest.approx(alice_balance_before + 25.3)


def test_entity_key_round_head_to_head_is_scoped_by_debate_and_pair() -> None:
    key = _entity_key(
        BetType.ROUND_HEAD_TO_HEAD,
        {"debate_id": 5, "team_a_id": 20, "team_b_id": 10, "predicted_higher_id": 20},
    )
    assert key == "debate:5:pair:10:20"
    # Order of team_a_id/team_b_id in the payload shouldn't matter -- same pair, same key.
    same_pair_swapped = _entity_key(
        BetType.ROUND_HEAD_TO_HEAD,
        {"debate_id": 5, "team_a_id": 10, "team_b_id": 20, "predicted_higher_id": 10},
    )
    assert same_pair_swapped == key


async def test_round_head_to_head_settles_base_pick_correctly(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_1, debate_a, _debate_b, teams = await _make_round_with_two_debates(db_session, tournament)
    # debate_a's two teams: teams[0] (OG) and teams[1] (OO). Give them a rank so the outcome
    # is resolvable.
    debate_a_teams = (
        (await db_session.execute(select(DebateTeam).where(DebateTeam.debate_id == debate_a.id)))
        .scalars()
        .all()
    )
    for rank, dt in enumerate(debate_a_teams, start=1):
        dt.rank_in_debate = rank
    await db_session.flush()
    higher_team_id = next(dt.team_id for dt in debate_a_teams if dt.rank_in_debate == 1)
    lower_team_id = next(dt.team_id for dt in debate_a_teams if dt.rank_in_debate == 2)

    market = await _make_market(
        db_session, tournament, BetType.ROUND_HEAD_TO_HEAD, target_round_id=round_1.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    db_session.add_all(
        [
            _prediction(
                BetType.ROUND_HEAD_TO_HEAD, market_id=market.id, user_id=alice.id,
                payload={
                    "debate_id": debate_a.id, "team_a_id": higher_team_id,
                    "team_b_id": lower_team_id, "predicted_higher_id": higher_team_id,
                },
            ),
            _prediction(
                BetType.ROUND_HEAD_TO_HEAD, market_id=market.id, user_id=bob.id,
                payload={
                    "debate_id": debate_a.id, "team_a_id": higher_team_id,
                    "team_b_id": lower_team_id, "predicted_higher_id": lower_team_id,
                },
            ),
        ]
    )
    await db_session.commit()
    alice_balance_before = alice.balance

    assert await settle_market(db_session, market) is True
    await db_session.commit()

    predictions = (
        (await db_session.execute(select(Prediction).order_by(Prediction.user_id))).scalars().all()
    )
    by_user = {p.user_id: p for p in predictions}
    # Pieza 3: pari-mutuel payout from the pair's own pool, not stake * frozen odds.
    assert by_user[alice.id].points_awarded == pytest.approx(17.9)
    assert by_user[bob.id].points_awarded == 0.0

    await db_session.refresh(alice)
    assert alice.balance == pytest.approx(alice_balance_before + 17.9)


async def test_round_head_to_head_sub_bet_is_all_or_nothing(db_session) -> None:
    """Regression guard for the exact product decision confirmed for this feature: getting the
    base pick right but the rank-gap sub-bet wrong must zero out the ENTIRE payout, not just
    skip the bonus -- same rule as missing any leg of a parlay."""
    tournament = await _make_tournament(db_session)
    round_1, debate_a, _debate_b, teams = await _make_round_with_two_debates(db_session, tournament)
    debate_a_teams = (
        (await db_session.execute(select(DebateTeam).where(DebateTeam.debate_id == debate_a.id)))
        .scalars()
        .all()
    )
    for rank, dt in enumerate(debate_a_teams, start=1):
        dt.rank_in_debate = rank
    await db_session.flush()
    higher_team_id = next(dt.team_id for dt in debate_a_teams if dt.rank_in_debate == 1)
    lower_team_id = next(dt.team_id for dt in debate_a_teams if dt.rank_in_debate == 2)
    actual_gap = 1  # only two teams in this synthetic debate -> gap is always 1

    market = await _make_market(
        db_session, tournament, BetType.ROUND_HEAD_TO_HEAD, target_round_id=round_1.id
    )
    winner_correct_gap = await _make_user(db_session, "correct@example.com")
    winner_wrong_gap = await _make_user(db_session, "wronggap@example.com")

    base_payload = {
        "debate_id": debate_a.id, "team_a_id": higher_team_id, "team_b_id": lower_team_id,
        "predicted_higher_id": higher_team_id,
    }
    db_session.add_all(
        [
            _prediction(
                BetType.ROUND_HEAD_TO_HEAD, market_id=market.id, user_id=winner_correct_gap.id,
                payload={**base_payload, "sub_bet": {"rank_gap": actual_gap}},
                stake_amount=10.0, odds=2.0, sub_bet_odds=3.0,
            ),
            _prediction(
                BetType.ROUND_HEAD_TO_HEAD, market_id=market.id, user_id=winner_wrong_gap.id,
                payload={**base_payload, "sub_bet": {"rank_gap": actual_gap + 1}},
                stake_amount=10.0, odds=2.0, sub_bet_odds=3.0,
            ),
        ]
    )
    await db_session.commit()

    assert await settle_market(db_session, market) is True
    await db_session.commit()

    predictions = (
        (await db_session.execute(select(Prediction).order_by(Prediction.user_id))).scalars().all()
    )
    by_user = {p.user_id: p for p in predictions}

    # Pieza 3: base is now the pari-mutuel ratio (not frozen odds=2.0), multiplied by
    # sub_bet_odds(3) exactly as before -- sub-bets deliberately stay a fixed multiplier on top.
    correct = by_user[winner_correct_gap.id]
    assert correct.points_awarded == pytest.approx(49.5)
    assert correct.sub_bet_status == PredictionStatus.SETTLED
    assert correct.sub_bet_points_awarded == pytest.approx(49.5)

    wrong = by_user[winner_wrong_gap.id]
    assert wrong.points_awarded == 0.0  # base was right but modifier missed -> ALL lost
    assert wrong.sub_bet_status == PredictionStatus.SETTLED
    assert wrong.sub_bet_points_awarded == 0.0


async def test_team_break_sub_bet_exact_rank_is_all_or_nothing(db_session) -> None:
    tournament = await _make_tournament(db_session)
    category = BreakCategory(tournament_id=tournament.id, name="Open", slug="open", break_size=2)
    db_session.add(category)
    await db_session.flush()
    team_1 = Team(tournament_id=tournament.id, external_id=1, name="Team 1")
    team_2 = Team(tournament_id=tournament.id, external_id=2, name="Team 2")
    db_session.add_all([team_1, team_2])
    await db_session.flush()
    db_session.add_all(
        [
            Break(
                tournament_id=tournament.id, break_category_id=category.id, team_id=team_1.id,
                rank=1,
            ),
            Break(
                tournament_id=tournament.id, break_category_id=category.id, team_id=team_2.id,
                rank=2,
            ),
        ]
    )
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.TEAM_BREAK, target_break_category_id=category.id
    )
    correct_rank = await _make_user(db_session, "correct-rank@example.com")
    wrong_rank = await _make_user(db_session, "wrong-rank@example.com")

    db_session.add_all(
        [
            _prediction(
                BetType.TEAM_BREAK, market_id=market.id, user_id=correct_rank.id,
                payload={"team_id": team_1.id, "sub_bet": {"exact_rank": 1}},
                stake_amount=10.0, odds=2.0, sub_bet_odds=5.0,
            ),
            _prediction(
                BetType.TEAM_BREAK, market_id=market.id, user_id=wrong_rank.id,
                payload={"team_id": team_1.id, "sub_bet": {"exact_rank": 2}},
                stake_amount=10.0, odds=2.0, sub_bet_odds=5.0,
            ),
        ]
    )
    await db_session.commit()

    assert await settle_market(db_session, market) is True
    await db_session.commit()

    predictions = {
        p.user_id: p for p in (await db_session.execute(select(Prediction))).scalars().all()
    }
    correct = predictions[correct_rank.id]
    assert correct.points_awarded == 100.0  # stake(10) * odds(2) * sub_bet_odds(5)
    assert correct.sub_bet_status == PredictionStatus.SETTLED
    assert correct.sub_bet_points_awarded == 100.0

    wrong = predictions[wrong_rank.id]
    assert wrong.points_awarded == 0.0  # team_1 broke (base won) but wrong exact rank -> all lost
    assert wrong.sub_bet_status == PredictionStatus.SETTLED
    assert wrong.sub_bet_points_awarded == 0.0


async def _make_round_winner_debate_with_speakers(db_session, tournament):
    """One debate, 2 teams, and 2 speakers on the team the tests bet on -- enough to exercise
    round_winner's deferred speaker-points sub-bet without needing the other bet types'
    4-team-BP-debate shape."""
    round_1 = Round(
        tournament_id=tournament.id, seq=1, name="Round 1", stage=RoundStage.PRELIMINARY,
        status=RoundStatus.RELEASED,
    )
    db_session.add(round_1)
    await db_session.flush()
    winning_team = Team(tournament_id=tournament.id, external_id=1, name="Winning Team")
    other_team = Team(tournament_id=tournament.id, external_id=2, name="Other Team")
    db_session.add_all([winning_team, other_team])
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    winning_debate_team = DebateTeam(
        debate_id=debate.id, team_id=winning_team.id, position=BPPosition.OPENING_GOVERNMENT,
    )
    other_debate_team = DebateTeam(
        debate_id=debate.id, team_id=other_team.id, position=BPPosition.OPENING_OPPOSITION,
    )
    db_session.add_all([winning_debate_team, other_debate_team])
    await db_session.flush()
    speakers = [
        Speaker(tournament_id=tournament.id, team_id=winning_team.id, name=f"Speaker {i}")
        for i in (1, 2)
    ]
    db_session.add_all(speakers)
    await db_session.flush()
    db_session.add_all(
        [
            SpeakerScore(
                debate_team_id=winning_debate_team.id, speaker_id=speakers[0].id,
                role=SpeakerRole.PM, score=None,
            ),
            SpeakerScore(
                debate_team_id=winning_debate_team.id, speaker_id=speakers[1].id,
                role=SpeakerRole.DPM, score=None,
            ),
        ]
    )
    await db_session.flush()
    return (
        round_1, debate, winning_team, other_team, winning_debate_team, other_debate_team,
        speakers,
    )


async def test_round_winner_sub_bet_pays_base_then_settles_deferred_once_scores_arrive(
    db_session,
) -> None:
    """Regression guard for the exact trap the plan called out: by the time a tournament
    finally releases withheld speaker points, the round_winner market has typically been
    SETTLED for a long time already -- settle_pending_sub_bets must find and resolve the
    sub-bet anyway, without depending on BetMarket.status."""
    tournament = await _make_tournament(db_session)
    (
        round_1, debate, winning_team, _other_team, winning_debate_team, other_debate_team,
        speakers,
    ) = await _make_round_winner_debate_with_speakers(db_session, tournament)
    winning_debate_team.rank_in_debate = 1
    other_debate_team.rank_in_debate = 2
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=round_1.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    alice_balance_before = alice.balance
    db_session.add(
        _prediction(
            BetType.ROUND_WINNER, market_id=market.id, user_id=alice.id,
            payload={
                "debate_id": debate.id, "team_id": winning_team.id,
                "sub_bet": {
                    "speaker_scores": [
                        {"speaker_id": speakers[0].id, "points": 76.0},
                        {"speaker_id": speakers[1].id, "points": 75.5},
                    ]
                },
            },
            stake_amount=10.0, odds=2.0, sub_bet_odds=15.0,
        )
    )
    await db_session.commit()

    assert await settle_market(db_session, market) is True
    await db_session.commit()

    prediction = (await db_session.execute(select(Prediction))).scalar_one()
    assert prediction.status == PredictionStatus.SETTLED
    # Pieza 3: base is the pari-mutuel ratio (13.4 = 10 stake * 1.34 ratio), not stake * frozen
    # odds=2.0.
    assert prediction.points_awarded == pytest.approx(13.4)
    assert prediction.sub_bet_status == PredictionStatus.OPEN
    assert prediction.sub_bet_points_awarded is None
    assert alice.balance == pytest.approx(alice_balance_before + 13.4)
    # The trap: the market is ALREADY settled here, same as every round_winner market will be
    # by the time speaker points actually show up.
    assert market.status == BetMarketStatus.SETTLED

    # Speaker points still withheld -- nothing resolvable yet.
    assert await settle_pending_sub_bets(db_session, tournament.id) == 0
    await db_session.commit()
    assert prediction.sub_bet_status == PredictionStatus.OPEN

    # Tab finally releases the real scores, matching the guess exactly.
    scores = (await db_session.execute(select(SpeakerScore))).scalars().all()
    for score in scores:
        score.score = 76.0 if score.speaker_id == speakers[0].id else 75.5
    await db_session.flush()

    assert await settle_pending_sub_bets(db_session, tournament.id) == 1
    await db_session.commit()

    # settle_pending_sub_bets derives the same effective ratio the base already paid with
    # (points_awarded / stake_amount = 1.34) rather than the frozen odds -- see that function's
    # comment on why, to guarantee the bonus is consistent with what the base actually paid.
    base_ratio = 1.34
    bonus = 10.0 * base_ratio * (15.0 - 1)  # stake * base_ratio * (sub_bet_odds - 1)
    assert prediction.sub_bet_status == PredictionStatus.SETTLED
    assert prediction.sub_bet_points_awarded == pytest.approx(bonus)
    assert prediction.points_awarded == pytest.approx(13.4 + bonus)  # base + bonus folded
    assert alice.balance == pytest.approx(alice_balance_before + 13.4 + bonus)

    leaderboard = (
        await db_session.execute(
            select(LeaderboardEntry).where(LeaderboardEntry.user_id == alice.id)
        )
    ).scalar_one()
    assert leaderboard.total_points == pytest.approx((13.4 + bonus) - 10.0)  # net = payout-stake


async def test_round_winner_sub_bet_settles_as_a_loss_immediately_when_base_loses(
    db_session,
) -> None:
    """The modifier is about the WINNING team's speakers -- if the picked team never won, there
    is nothing left to wait for, so this must settle right away rather than sit OPEN forever."""
    tournament = await _make_tournament(db_session)
    (
        round_1, debate, winning_team, other_team, winning_debate_team, other_debate_team,
        speakers,
    ) = await _make_round_winner_debate_with_speakers(db_session, tournament)
    # other_team wins instead of winning_team.
    other_debate_team.rank_in_debate = 1
    winning_debate_team.rank_in_debate = 2
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=round_1.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add(
        _prediction(
            BetType.ROUND_WINNER, market_id=market.id, user_id=alice.id,
            payload={
                "debate_id": debate.id, "team_id": winning_team.id,
                "sub_bet": {
                    "speaker_scores": [
                        {"speaker_id": speakers[0].id, "points": 76.0},
                        {"speaker_id": speakers[1].id, "points": 75.5},
                    ]
                },
            },
            stake_amount=10.0, odds=2.0, sub_bet_odds=15.0,
        )
    )
    await db_session.commit()

    assert await settle_market(db_session, market) is True
    await db_session.commit()

    prediction = (await db_session.execute(select(Prediction))).scalar_one()
    assert prediction.points_awarded == 0.0
    assert prediction.sub_bet_status == PredictionStatus.SETTLED
    assert prediction.sub_bet_points_awarded == 0.0
    # Nothing left pending -- settle_pending_sub_bets shouldn't even pick this one up.
    assert await settle_pending_sub_bets(db_session, tournament.id) == 0


async def test_round_winner_sub_bet_settles_as_a_loss_when_speaker_scores_are_wrong(
    db_session,
) -> None:
    tournament = await _make_tournament(db_session)
    (
        round_1, debate, winning_team, _other_team, winning_debate_team, other_debate_team,
        speakers,
    ) = await _make_round_winner_debate_with_speakers(db_session, tournament)
    winning_debate_team.rank_in_debate = 1
    other_debate_team.rank_in_debate = 2
    await db_session.flush()

    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=round_1.id
    )
    alice = await _make_user(db_session, "alice@example.com")
    alice_balance_before = alice.balance
    db_session.add(
        _prediction(
            BetType.ROUND_WINNER, market_id=market.id, user_id=alice.id,
            payload={
                "debate_id": debate.id, "team_id": winning_team.id,
                "sub_bet": {
                    "speaker_scores": [
                        {"speaker_id": speakers[0].id, "points": 76.0},
                        {"speaker_id": speakers[1].id, "points": 75.5},
                    ]
                },
            },
            stake_amount=10.0, odds=2.0, sub_bet_odds=15.0,
        )
    )
    await db_session.commit()

    assert await settle_market(db_session, market) is True
    await db_session.commit()

    prediction = (await db_session.execute(select(Prediction))).scalar_one()
    assert prediction.sub_bet_status == PredictionStatus.OPEN

    scores = (await db_session.execute(select(SpeakerScore))).scalars().all()
    for score in scores:
        # Real scores don't match the guess.
        score.score = 70.0 if score.speaker_id == speakers[0].id else 70.0
    await db_session.flush()

    assert await settle_pending_sub_bets(db_session, tournament.id) == 1
    await db_session.commit()

    assert prediction.sub_bet_status == PredictionStatus.SETTLED
    assert prediction.sub_bet_points_awarded == 0.0
    # Pieza 3: base payout stands at its pari-mutuel ratio (same fixture/stake as the sibling
    # "scores arrive correctly" test above -> same 13.4), no bonus added since the guess missed.
    assert prediction.points_awarded == pytest.approx(13.4)
    assert alice.balance == pytest.approx(alice_balance_before + 13.4)


async def test_round_winner_sub_bet_odds_rejects_malformed_speaker_scores(db_session) -> None:
    from app.services.odds_service import quote_sub_bet_odds

    tournament = await _make_tournament(db_session)
    (round_1, debate, winning_team, _other, _wdt, _odt, speakers) = (
        await _make_round_winner_debate_with_speakers(db_session, tournament)
    )
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=round_1.id
    )
    base_payload = {"debate_id": debate.id, "team_id": winning_team.id}

    # Only one speaker named -- a BP team always has 2.
    one_speaker_sub_bet = {
        "speaker_scores": [{"speaker_id": speakers[0].id, "points": 76.0}]
    }
    with pytest.raises(ValueError):
        await quote_sub_bet_odds(
            db_session, market, {**base_payload, "sub_bet": one_speaker_sub_bet}
        )

    # Missing "points" on one entry.
    with pytest.raises(ValueError):
        await quote_sub_bet_odds(
            db_session, market,
            {
                **base_payload,
                "sub_bet": {
                    "speaker_scores": [
                        {"speaker_id": speakers[0].id, "points": 76.0},
                        {"speaker_id": speakers[1].id},
                    ]
                },
            },
        )

    # Well-formed -- flat admin-tunable price, no DB-dependent math.
    odds = await quote_sub_bet_odds(
        db_session, market,
        {
            **base_payload,
            "sub_bet": {
                "speaker_scores": [
                    {"speaker_id": speakers[0].id, "points": 76.0},
                    {"speaker_id": speakers[1].id, "points": 75.5},
                ]
            },
        },
    )
    assert odds == 15.0

    # No sub_bet at all -- None, same as every other bet type.
    assert await quote_sub_bet_odds(db_session, market, base_payload) is None


def test_validate_market_creation_blocks_unsettleable_bet_types_on_elimination_rounds() -> None:
    """Tabbycat records only advanced/not-advanced for an out-round -- `rank_in_debate` stays
    NULL forever (verified against the real tab), so a full-call or head-to-head market on an
    elimination round would take bets it could never pay out. Refused at creation instead."""
    tournament = Tournament(
        name="T", slug="t", source_base_url="https://x", source_slug="o",
        status=TournamentStatus.ELIMINATIONS,
    )
    for bet_type in (BetType.ROUND_FULL_CALL, BetType.ROUND_HEAD_TO_HEAD):
        with pytest.raises(MarketCreationError):
            validate_market_creation(
                tournament,
                bet_type,
                target_round_id=1,
                target_break_category_id=None,
                target_round_stage=RoundStage.ELIMINATION,
            )
        # The very same type is fine on a preliminary round.
        validate_market_creation(
            tournament,
            bet_type,
            target_round_id=1,
            target_break_category_id=None,
            target_round_stage=RoundStage.PRELIMINARY,
        )


def test_validate_market_creation_allows_round_winner_on_elimination_rounds() -> None:
    """round_winner is the one round-scoped type that DOES resolve on an out-round: it falls
    back to "did my team advance" (see build_prediction_specific_outcome)."""
    tournament = Tournament(
        name="T", slug="t", source_base_url="https://x", source_slug="o",
        status=TournamentStatus.ELIMINATIONS,
    )
    validate_market_creation(
        tournament,
        BetType.ROUND_WINNER,
        target_round_id=1,
        target_break_category_id=None,
        target_round_stage=RoundStage.ELIMINATION,
    )  # does not raise


async def _make_elimination_round(db_session, tournament, *, num_debates: int):
    """An out-round with `num_debates` rooms of 4 teams each -- 8 rooms is an octofinal, 1 room
    is the grand final. `odds_service._advancing_count` reads the room count to decide whether 2
    teams advance per room or just 1."""
    elim = Round(
        tournament_id=tournament.id, seq=10, name="Octavos de Final",
        stage=RoundStage.ELIMINATION, status=RoundStatus.RELEASED,
    )
    db_session.add(elim)
    await db_session.flush()
    positions = (
        BPPosition.OPENING_GOVERNMENT, BPPosition.OPENING_OPPOSITION,
        BPPosition.CLOSING_GOVERNMENT, BPPosition.CLOSING_OPPOSITION,
    )
    debates, all_teams = [], []
    for d in range(num_debates):
        debate = Debate(tournament_id=tournament.id, round_id=elim.id, external_id=100 + d)
        db_session.add(debate)
        await db_session.flush()
        teams = [
            Team(tournament_id=tournament.id, external_id=1000 + d * 4 + i, name=f"T{d}-{i}")
            for i in range(4)
        ]
        db_session.add_all(teams)
        await db_session.flush()
        for team, position in zip(teams, positions, strict=True):
            db_session.add(DebateTeam(debate_id=debate.id, team_id=team.id, position=position))
        debates.append(debate)
        all_teams.append(teams)
    await db_session.flush()
    return elim, debates, all_teams


async def test_elimination_round_winner_prices_as_top_two_not_single_winner(db_session) -> None:
    """The arbitrage regression, end to end: in an octofinal 2 of 4 teams advance, so the four
    quoted odds must imply ~2.0 total probability. When they implied 1.0 (one-winner pricing),
    backing the whole room returned double the stake risk-free."""
    from app.services.odds_service import quote_odds

    tournament = await _make_tournament(db_session, status=TournamentStatus.ELIMINATIONS)
    elim, debates, all_teams = await _make_elimination_round(db_session, tournament, num_debates=8)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=elim.id
    )
    await db_session.commit()

    room, teams = debates[0], all_teams[0]
    implied = 0.0
    for team in teams:
        odds = await quote_odds(db_session, market, {"debate_id": room.id, "team_id": team.id})
        implied += 1 / odds
    assert implied == pytest.approx(2.0, rel=0.05)


async def test_grand_final_round_winner_still_prices_as_a_single_winner(db_session) -> None:
    """A one-room out-round is the grand final: exactly one team advances, so the book goes back
    to summing to 1.0 -- the top-N pricing must not blanket-double every elimination round."""
    from app.services.odds_service import quote_odds

    tournament = await _make_tournament(db_session, status=TournamentStatus.ELIMINATIONS)
    elim, debates, all_teams = await _make_elimination_round(db_session, tournament, num_debates=1)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=elim.id
    )
    await db_session.commit()

    implied = 0.0
    for team in all_teams[0]:
        odds = await quote_odds(
            db_session, market, {"debate_id": debates[0].id, "team_id": team.id}
        )
        implied += 1 / odds
    assert implied == pytest.approx(1.0, rel=0.05)


# --- ROUND_WINNER's exact-pair pick: elimination-only "team_ids" payload shape -----------
# Folded in from what used to be the standalone ROUND_ADVANCING_PAIR bet_type -- same market,
# same round, a ROUND_WINNER payload just optionally names 2 teams instead of 1. There is no
# creation-time "must be an elimination round" check anymore (unlike the old bet_type): a
# ROUND_WINNER market can be created for any round, and a `team_ids` payload is only accepted
# at quote/bet time, gated by `_advancing_count(debate_id) == 2` (see the rejection test below).


async def test_round_winner_pair_pick_prices_all_six_pairs_close_to_one(db_session) -> None:
    """No pool blending peculiarities: with zero stakes on a fresh market, the 6 possible pairs'
    quoted odds should still imply a total probability close to 1.0 -- exactly one pair is truly
    "the" advancing pair, so this is a proper one-winner-among-six market."""
    from app.services.odds_service import quote_odds

    tournament = await _make_tournament(db_session, status=TournamentStatus.ELIMINATIONS)
    elim, debates, all_teams = await _make_elimination_round(db_session, tournament, num_debates=8)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=elim.id
    )
    await db_session.commit()

    room, teams = debates[0], all_teams[0]
    implied = 0.0
    for a, b in itertools.combinations(teams, 2):
        odds = await quote_odds(
            db_session, market, {"debate_id": room.id, "team_ids": [a.id, b.id]}
        )
        implied += 1 / odds
    assert implied == pytest.approx(1.0, rel=0.05)


async def test_round_winner_pair_pick_quote_rejects_a_single_advancing_room(db_session) -> None:
    """The grand final sends 1 team through, not 2 -- 'which pair advances' is meaningless
    there, so pricing it must fail loudly rather than silently return a bogus number."""
    from app.services.odds_service import UnpriceableMarketError, quote_odds

    tournament = await _make_tournament(db_session, status=TournamentStatus.ELIMINATIONS)
    # num_debates=1 is exactly what makes this a single-room final -- _advancing_count infers
    # the round's advancing-count from how many debates it has, and a 1-debate round is the
    # grand final shape (1 advances), not a normal 8-of-32 octofinal room (2 advance).
    elim, debates, all_teams = await _make_elimination_round(db_session, tournament, num_debates=1)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=elim.id
    )
    await db_session.commit()
    room, teams = debates[0], all_teams[0]
    with pytest.raises(UnpriceableMarketError):
        await quote_odds(
            db_session, market, {"debate_id": room.id, "team_ids": [teams[0].id, teams[1].id]}
        )


async def test_round_winner_pair_pick_settles_the_exact_advancing_pair_and_only_that_pair(
    db_session,
) -> None:
    """End-to-end: place a bet on the real advancing pair and on a wrong pair, settle the
    debate, confirm only the correct pair pays out."""
    tournament = await _make_tournament(db_session, status=TournamentStatus.ELIMINATIONS)
    elim, debates, all_teams = await _make_elimination_round(db_session, tournament, num_debates=8)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=elim.id
    )
    room, teams = debates[0], all_teams[0]
    advancing = teams[:2]
    for dt in (
        await db_session.execute(
            select(DebateTeam).where(DebateTeam.debate_id == room.id)
        )
    ).scalars():
        dt.advanced = dt.team_id in {t.id for t in advancing}
    room.status = DebateStatus.CONFIRMED

    alice = await _make_user(db_session, "alice-pair@example.com")
    bob = await _make_user(db_session, "bob-pair@example.com")
    correct = _prediction(
        BetType.ROUND_WINNER,
        market_id=market.id, user_id=alice.id,
        payload={"debate_id": room.id, "team_ids": [advancing[0].id, advancing[1].id]},
        stake_amount=10.0, odds=3.0,
    )
    wrong = _prediction(
        BetType.ROUND_WINNER,
        market_id=market.id, user_id=bob.id,
        payload={"debate_id": room.id, "team_ids": [teams[2].id, teams[3].id]},
        stake_amount=10.0, odds=3.0,
    )
    db_session.add_all([correct, wrong])
    await db_session.commit()

    settled = await settle_market(db_session, market)
    await db_session.commit()

    # Both predictions on this market target the one room that's resolved -- nobody bet on the
    # other 7 rooms of this octofinal, so there's nothing else pending and the market settles.
    assert settled is True
    await db_session.refresh(correct)
    await db_session.refresh(wrong)
    assert correct.status == PredictionStatus.SETTLED
    # Pieza 3: pari-mutuel exact-pair payout (ELIMINATION_SEED), not stake * frozen odds=3.0.
    assert correct.points_awarded == pytest.approx(26.4)
    assert wrong.status == PredictionStatus.SETTLED
    assert wrong.points_awarded == 0.0


async def test_round_winner_allows_up_to_two_independent_single_team_picks_per_room(
    db_session,
) -> None:
    """A user can back 2 different teams independently in the same room (each gets its own
    entity_key -- see _entity_key), so if one doesn't advance the other still pays. A 3rd
    distinct team in the same room is rejected; re-picking one of the 2 already held is still
    just an edit, not a 3rd pick."""
    from app.services.betting_service import TooManyPicksError, place_prediction

    tournament = await _make_tournament(db_session, status=TournamentStatus.ELIMINATIONS)
    elim, debates, all_teams = await _make_elimination_round(db_session, tournament, num_debates=8)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=elim.id,
        status=BetMarketStatus.OPEN,
    )
    room, teams = debates[0], all_teams[0]
    alice = await _make_user(db_session, "alice-cap@example.com")
    await db_session.commit()

    await place_prediction(
        db_session, market, alice, {"debate_id": room.id, "team_id": teams[0].id}, 10.0
    )
    await place_prediction(
        db_session, market, alice, {"debate_id": room.id, "team_id": teams[1].id}, 10.0
    )
    await db_session.commit()

    with pytest.raises(TooManyPicksError):
        await place_prediction(
            db_session, market, alice, {"debate_id": room.id, "team_id": teams[2].id}, 10.0
        )

    # Re-picking (editing) one of the 2 already-held teams is not a 3rd pick.
    await place_prediction(
        db_session, market, alice, {"debate_id": room.id, "team_id": teams[0].id}, 15.0
    )
    await db_session.commit()

    open_predictions = (
        await db_session.execute(
            select(Prediction).where(
                Prediction.bet_market_id == market.id,
                Prediction.status == PredictionStatus.OPEN,
            )
        )
    ).scalars().all()
    assert len(open_predictions) == 2
    assert {p.stake_amount for p in open_predictions} == {15.0, 10.0}


async def test_round_winner_speaker_points_sub_bet_rejected_on_elimination_round(
    db_session,
) -> None:
    """Tabbycat never publishes per-speaker scores for an elimination out-round -- the
    sub-bet can never resolve there, so placing one must fail up front instead of silently
    accepting a bet that could never pay its bonus."""
    from app.services.odds_service import quote_sub_bet_odds

    tournament = await _make_tournament(db_session, status=TournamentStatus.ELIMINATIONS)
    elim, debates, all_teams = await _make_elimination_round(db_session, tournament, num_debates=8)
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=elim.id
    )
    room, teams = debates[0], all_teams[0]
    await db_session.commit()

    payload = {
        "debate_id": room.id,
        "team_id": teams[0].id,
        "sub_bet": {
            "speaker_scores": [
                {"speaker_id": 1, "points": 76.0},
                {"speaker_id": 2, "points": 75.0},
            ]
        },
    }
    with pytest.raises(ValueError):
        await quote_sub_bet_odds(db_session, market, payload)


async def test_round_winner_speaker_points_sub_bet_still_works_on_preliminary_round(
    db_session,
) -> None:
    """Regression guard for the elimination-round gate above: a preliminary-round ROUND_WINNER
    sub-bet must keep pricing exactly as before."""
    from app.services.odds_service import DEFAULT_SPEAKER_POINTS_SUB_BET_ODDS, quote_sub_bet_odds

    tournament = await _make_tournament(db_session)
    round_ = Round(tournament_id=tournament.id, seq=1, name="Ronda 1", stage=RoundStage.PRELIMINARY)
    db_session.add(round_)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    market = await _make_market(
        db_session, tournament, BetType.ROUND_WINNER, target_round_id=round_.id
    )
    await db_session.commit()

    payload = {
        "debate_id": debate.id,
        "team_id": 1,
        "sub_bet": {
            "speaker_scores": [
                {"speaker_id": 1, "points": 76.0},
                {"speaker_id": 2, "points": 75.0},
            ]
        },
    }
    odds = await quote_sub_bet_odds(db_session, market, payload)
    assert odds == DEFAULT_SPEAKER_POINTS_SUB_BET_ODDS
