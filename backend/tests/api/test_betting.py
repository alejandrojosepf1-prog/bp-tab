import datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BreakCategory,
    Debate,
    DebateTeam,
    Round,
    Speaker,
    SpeakerScore,
    Team,
    TeamBreakCategory,
    Tournament,
)
from app.models.enums import (
    BPPosition,
    RoundStage,
    RoundStatus,
    SpeakerRole,
    TournamentStatus,
    UserRole,
)
from tests.api.conftest import auth_headers, make_user

NOW = datetime.datetime.now(datetime.timezone.utc)
PAST = NOW - datetime.timedelta(days=1)
FUTURE = NOW + datetime.timedelta(days=1)


async def _make_tournament_with_team(db_session: AsyncSession) -> tuple[Tournament, Team, Team]:
    """Two teams, not one: odds pricing needs at least a 2-team field to price anything (a
    lone-candidate market is a nonsensical "certain to win" case), and most of these tests just
    need *a* second, real team for the "wrong pick" side of a bet.

    status=UPCOMING: every test in this module creates a `champion` market, which is now only
    creatable pre-tournament (see test_champion_market_lifecycle_and_pretournament_gate for the
    dedicated coverage of that gate itself) -- none of these tests are actually exercising
    in-progress-tournament behavior, so UPCOMING is the correct default rather than an arbitrary
    leftover status."""
    tournament = Tournament(
        name="Betting Cup",
        slug="betting-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.UPCOMING,
    )
    db_session.add(tournament)
    await db_session.flush()
    team = Team(tournament_id=tournament.id, external_id=1, name="Champions Team")
    other_team = Team(tournament_id=tournament.id, external_id=2, name="Runners Up")
    db_session.add_all([team, other_team])
    await db_session.commit()
    await db_session.refresh(tournament)
    await db_session.refresh(team)
    await db_session.refresh(other_team)
    return tournament, team, other_team


async def test_create_bet_market_requires_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    user = await make_user(db_session, email="notadmin@example.com", role=UserRole.USER)

    response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 403


async def test_full_champion_market_lifecycle_settles_and_updates_leaderboard(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, team, other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin@example.com", role=UserRole.ADMIN)
    alice = await make_user(db_session, email="alice@example.com", display_name="Alice")
    bob = await make_user(db_session, email="bob@example.com", display_name="Bob")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201
    market = create_response.json()
    assert market["status"] == "open"
    market_id = market["id"]

    # Alice predicts correctly, Bob predicts incorrectly.
    alice_prediction = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 100.0},
        headers=auth_headers(alice),
    )
    assert alice_prediction.status_code == 201
    assert alice_prediction.json()["status"] == "open"
    assert alice_prediction.json()["points_awarded"] is None

    bob_prediction = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": other_team.id}, "stake_amount": 50.0},
        headers=auth_headers(bob),
    )
    assert bob_prediction.status_code == 201

    # /predictions/me returns a list now (a user can hold one OPEN prediction per entity within
    # a market, not just one per market) -- reflects what each user just submitted.
    me_response = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(alice)
    )
    assert me_response.status_code == 200
    assert len(me_response.json()) == 1
    assert me_response.json()[0]["payload"] == {"team_id": team.id}

    # Re-submitting updates the same row rather than creating a second one (unique constraint).
    alice_resubmit = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 100.0},
        headers=auth_headers(alice),
    )
    assert alice_resubmit.status_code == 201
    assert alice_resubmit.json()["id"] == alice_prediction.json()["id"]

    # Simulate the tournament finishing (this would normally happen via the scraper/ingestion).
    tournament_row = await db_session.get(Tournament, tournament.id)
    tournament_row.champion_team_id = team.id
    await db_session.commit()

    settle_response = await client.post(
        f"/api/v1/bet-markets/{market_id}/settle", json={}, headers=auth_headers(admin)
    )
    assert settle_response.status_code == 200
    assert settle_response.json() == {"settled": True}

    # A 2-team field with no debates played yet prices both teams at a fair 50/50 prior
    # (power=0 for both) -- see app.domain.odds's pari-mutuel-with-seed model. Alice's odds get
    # LOCKED at her final (resubmit) call, which happens after Bob has already staked 50 on the
    # loser: her own prior 100-stake is excluded from the pool she's priced against (see
    # odds_service._open_stakes's exclude_user_id), so that pool is just Bob's 50 on the OTHER
    # team, none of it on Alice's pick. pari_mutuel_probability(0, 50, 0.5, seed=200) = 100/250 =
    # 0.4 -> decimal odds 1/0.4 = 2.5, the fair price with no margin taken. She staked 100 on the
    # winner, so she's paid stake * odds = 250; Bob staked 50 on the loser and gets nothing back.
    alice_after = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(alice)
    )
    assert alice_after.json()[0]["status"] == "settled"
    assert alice_after.json()[0]["odds"] == 2.5
    assert alice_after.json()[0]["points_awarded"] == 250.0

    bob_after = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(bob)
    )
    assert bob_after.json()[0]["points_awarded"] == 0.0

    leaderboard_response = await client.get(f"/api/v1/tournaments/{tournament.id}/leaderboard")
    assert leaderboard_response.status_code == 200
    leaderboard = leaderboard_response.json()
    assert len(leaderboard) == 2
    top = leaderboard[0]
    assert top["user"]["display_name"] == "Alice"
    assert top["total_points"] == 150.0  # net profit: 250 payout - 100 stake
    assert top["rank"] == 1


async def test_prediction_requires_authentication(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, team, other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin2@example.com", role=UserRole.ADMIN)
    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 100.0},
    )
    assert response.status_code == 401


async def test_prediction_rejected_when_market_closed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, team, other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin3@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user4@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    patch_response = await client.patch(
        f"/api/v1/bet-markets/{market_id}",
        json={"status": "closed"},
        headers=auth_headers(admin),
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "closed"

    response = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 100.0},
        headers=auth_headers(user),
    )
    assert response.status_code == 400


async def test_prediction_rejected_when_past_closes_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, team, other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin4@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user5@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Already closed by time",
            "opens_at": (PAST - datetime.timedelta(days=2)).isoformat(),
            "closes_at": PAST.isoformat(),
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 100.0},
        headers=auth_headers(user),
    )
    assert response.status_code == 400


async def test_patch_bet_market_cannot_set_settled_directly(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin5@example.com", role=UserRole.ADMIN)

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/bet-markets/{market_id}",
        json={"status": "settled"},
        headers=auth_headers(admin),
    )
    assert response.status_code == 400


async def test_settle_requires_admin(client: AsyncClient, db_session: AsyncSession) -> None:
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin6@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user6@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/bet-markets/{market_id}/settle", json={}, headers=auth_headers(user)
    )
    assert response.status_code == 403


async def test_odds_move_with_the_pool_as_stakes_come_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Pari-mutuel-with-seed behavior visible from the API: a candidate nobody's backed prices
    at the fair 50/50 prior; once real money piles onto ONE side, that side's own quote shortens
    (more real money already agreeing with the pick) while the other side's quote lengthens."""
    tournament, team, other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin7@example.com", role=UserRole.ADMIN)
    # Explicit balances: this test is about large stakes overwhelming the 200-token seed, so the
    # stakes here (150 each) deliberately exceed the standard STARTING_BALANCE grant.
    alice = await make_user(
        db_session, email="alice2@example.com", display_name="Alice2", balance=1000.0
    )
    bob = await make_user(
        db_session, email="bob2@example.com", display_name="Bob2", balance=1000.0
    )
    carol = await make_user(db_session, email="carol2@example.com", display_name="Carol2")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    # Before anyone's bet, the quote is the fair 50/50 prior -- exactly 2.0, no margin shaved.
    initial_quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"team_id": team.id}},
        headers=auth_headers(carol),
    )
    assert initial_quote.json()["odds"] == 2.0

    # Alice and Bob both back `team` heavily -- their combined stake (300) starts to dominate
    # the 200-seed, so the crowd's conviction should shorten `team`'s price below the prior...
    await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 150.0},
        headers=auth_headers(alice),
    )
    await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 150.0},
        headers=auth_headers(bob),
    )

    team_quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"team_id": team.id}},
        headers=auth_headers(carol),
    )
    other_team_quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"team_id": other_team.id}},
        headers=auth_headers(carol),
    )
    # ...and lengthen `other_team`'s price (all the real money is against it now).
    assert team_quote.json()["odds"] < 2.0
    assert other_team_quote.json()["odds"] > 2.0


async def test_champion_market_creation_rejected_once_tournament_has_started(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    tournament.status = TournamentStatus.IN_PROGRESS
    await db_session.commit()
    admin = await make_user(db_session, email="admin8@example.com", role=UserRole.ADMIN)

    response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 400


async def test_round_scoped_market_creation_requires_target_round_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin9@example.com", role=UserRole.ADMIN)

    for bet_type in ("round_winner", "round_full_call"):
        response = await client.post(
            f"/api/v1/tournaments/{tournament.id}/bet-markets",
            json={
                "bet_type": bet_type,
                "label": "Ganador de la sala",
                "opens_at": PAST.isoformat(),
                "closes_at": FUTURE.isoformat(),
            },
            headers=auth_headers(admin),
        )
        assert response.status_code == 400


async def _make_full_call_debate(
    db_session: AsyncSession,
) -> tuple[Tournament, Round, Debate, list[Team]]:
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.RELEASED,
    )
    db_session.add(round_1)
    await db_session.flush()
    teams = [
        Team(tournament_id=tournament.id, external_id=100 + i, name=f"Debate Team {i}")
        for i in range(4)
    ]
    db_session.add_all(teams)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=500)
    db_session.add(debate)
    await db_session.flush()
    for team, position in zip(
        teams,
        [
            BPPosition.OPENING_GOVERNMENT,
            BPPosition.OPENING_OPPOSITION,
            BPPosition.CLOSING_GOVERNMENT,
            BPPosition.CLOSING_OPPOSITION,
        ],
        strict=True,
    ):
        db_session.add(DebateTeam(debate_id=debate.id, team_id=team.id, position=position))
    await db_session.commit()
    await db_session.refresh(round_1)
    await db_session.refresh(debate)
    return tournament, round_1, debate, teams


async def test_round_full_call_quote_and_place_via_api(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, round_1, debate, teams = await _make_full_call_debate(db_session)
    admin = await make_user(db_session, email="admin10@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user10@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "round_full_call",
            "label": "Call completo Ronda 1",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": round_1.id,
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201
    market_id = create_response.json()["id"]

    ordered_ids = [t.id for t in teams]
    quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"debate_id": debate.id, "team_ids": ordered_ids}},
        headers=auth_headers(user),
    )
    assert quote.status_code == 200
    assert quote.json()["odds"] > 1.0

    prediction = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={
            "payload": {"debate_id": debate.id, "team_ids": ordered_ids},
            "stake_amount": 10.0,
        },
        headers=auth_headers(user),
    )
    assert prediction.status_code == 201

    # Wrong number of teams / a team outside this debate is rejected as an invalid payload.
    bad_prediction = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={
            "payload": {"debate_id": debate.id, "team_ids": ordered_ids[:3]},
            "stake_amount": 10.0,
        },
        headers=auth_headers(user),
    )
    assert bad_prediction.status_code == 422


async def test_round_full_call_rejects_debate_from_a_different_round(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, round_1, debate, teams = await _make_full_call_debate(db_session)
    other_round = Round(
        tournament_id=tournament.id,
        seq=2,
        name="Round 2",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.RELEASED,
    )
    db_session.add(other_round)
    await db_session.commit()
    await db_session.refresh(other_round)

    admin = await make_user(db_session, email="admin11@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user11@example.com")
    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "round_full_call",
            "label": "Call completo Ronda 2",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": other_round.id,
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"debate_id": debate.id, "team_ids": [t.id for t in teams]}},
        headers=auth_headers(user),
    )
    assert quote.status_code == 422


async def test_top_speaker_position_quote_and_place_via_api(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    round_1 = Round(
        tournament_id=tournament.id, seq=1, name="Round 1", stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(round_1)
    await db_session.flush()
    team = Team(tournament_id=tournament.id, external_id=200, name="Speaker Team")
    db_session.add(team)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=600)
    db_session.add(debate)
    await db_session.flush()
    debate_team = DebateTeam(
        debate_id=debate.id, team_id=team.id, position=BPPosition.OPENING_GOVERNMENT,
        rank_in_debate=1,
    )
    db_session.add(debate_team)
    await db_session.flush()
    speaker_a = Speaker(tournament_id=tournament.id, team_id=team.id, name="Speaker A")
    speaker_b = Speaker(tournament_id=tournament.id, team_id=team.id, name="Speaker B")
    db_session.add_all([speaker_a, speaker_b])
    await db_session.flush()
    db_session.add(
        SpeakerScore(
            debate_team_id=debate_team.id, speaker_id=speaker_a.id, role=SpeakerRole.PM, score=85.0
        )
    )
    db_session.add(
        SpeakerScore(
            debate_team_id=debate_team.id, speaker_id=speaker_b.id, role=SpeakerRole.DPM, score=75.0
        )
    )
    await db_session.commit()

    admin = await make_user(db_session, email="admin12@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user12@example.com")
    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "top_speaker_position",
            "label": "Tabla de oradores",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201
    market_id = create_response.json()["id"]

    # The stronger speaker should be quoted shorter odds for finishing 1st than the weaker one.
    quote_a_first = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"speaker_id": speaker_a.id, "position": 1}},
        headers=auth_headers(user),
    )
    quote_b_first = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"speaker_id": speaker_b.id, "position": 1}},
        headers=auth_headers(user),
    )
    assert quote_a_first.json()["odds"] < quote_b_first.json()["odds"]

    prediction = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"speaker_id": speaker_a.id, "position": 1}, "stake_amount": 10.0},
        headers=auth_headers(user),
    )
    assert prediction.status_code == 201

    invalid_position = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"speaker_id": speaker_a.id, "position": 4}},
        headers=auth_headers(user),
    )
    assert invalid_position.status_code == 422


async def test_team_break_quote_prices_independently_per_team(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, team, other_team = await _make_tournament_with_team(db_session)
    category = BreakCategory(
        tournament_id=tournament.id, name="Open", slug="open", break_size=1
    )
    db_session.add(category)
    await db_session.flush()
    db_session.add_all(
        [
            TeamBreakCategory(team_id=team.id, break_category_id=category.id),
            TeamBreakCategory(team_id=other_team.id, break_category_id=category.id),
        ]
    )
    await db_session.commit()

    admin = await make_user(db_session, email="admin13@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user13@example.com")
    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "team_break",
            "label": "Quién rompe",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_break_category_id": category.id,
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201
    market_id = create_response.json()["id"]

    # No rounds played yet -- naive base rate: break_size(1) / num_teams(2) = 0.5 for BOTH teams
    # (see break_service.team_break_probability), NOT a softmax that would sum to 1 across them.
    quote_team = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"team_id": team.id}},
        headers=auth_headers(user),
    )
    quote_other = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"team_id": other_team.id}},
        headers=auth_headers(user),
    )
    assert quote_team.json()["odds"] == quote_other.json()["odds"]

    prediction = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 10.0},
        headers=auth_headers(user),
    )
    assert prediction.status_code == 201

    board = await client.get(f"/api/v1/bet-markets/{market_id}/board")
    assert board.status_code == 200
    board_body = board.json()
    assert board_body["pool_total"] == 10.0
    assert len(board_body["options"]) == 2  # both registered teams shown, staked or not
