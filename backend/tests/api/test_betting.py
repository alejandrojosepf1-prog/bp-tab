import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
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


async def test_reopening_an_expired_market_requires_a_new_closing_time(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression: PATCH status=open on a market whose closes_at already passed used to
    "succeed" while leaving the market unbettable -- POST .../predictions kept rejecting every
    bet since `now >= closes_at` still held, so the market looked reopened but wasn't."""
    tournament, team, _other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin-reopen@example.com", role=UserRole.ADMIN)
    bettor = await make_user(db_session, email="bettor-reopen@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Who wins it all?",
            "opens_at": (PAST - datetime.timedelta(days=2)).isoformat(),
            "closes_at": PAST.isoformat(),  # already in the past at creation
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    # The market opens as "open" by default even though its closes_at already passed -- close it
    # first, the way an admin actually would after noticing bets are silently being rejected.
    close_response = await client.patch(
        f"/api/v1/bet-markets/{market_id}",
        json={"status": "closed"},
        headers=auth_headers(admin),
    )
    assert close_response.status_code == 200

    # Reopening with no new closes_at is rejected outright...
    reject_response = await client.patch(
        f"/api/v1/bet-markets/{market_id}",
        json={"status": "open"},
        headers=auth_headers(admin),
    )
    assert reject_response.status_code == 400

    # ...and a bet still can't be placed (status never actually changed).
    still_closed = await client.get(f"/api/v1/tournaments/{tournament.id}/bet-markets")
    assert still_closed.json()[0]["status"] == "closed"

    # Reopening WITH a fresh future closes_at succeeds, and predictions work again.
    reopen_response = await client.patch(
        f"/api/v1/bet-markets/{market_id}",
        json={"status": "open", "closes_at": FUTURE.isoformat()},
        headers=auth_headers(admin),
    )
    assert reopen_response.status_code == 200
    assert reopen_response.json()["status"] == "open"
    reopened_closes_at = datetime.datetime.fromisoformat(reopen_response.json()["closes_at"])
    if reopened_closes_at.tzinfo is None:
        reopened_closes_at = reopened_closes_at.replace(tzinfo=datetime.timezone.utc)
    assert reopened_closes_at == FUTURE

    bet_response = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 10.0},
        headers=auth_headers(bettor),
    )
    assert bet_response.status_code == 201


async def _make_round_with_two_debates(
    db_session: AsyncSession,
) -> tuple[Tournament, Round, Debate, Debate, list[Team]]:
    """Two 2-team debates in the same round -- enough to exercise market_board's generic
    per-payload fallback (round_winner/round_full_call/top_speaker_position) with more than one
    distinct payload, which is exactly the path with the N+1 characterized below."""
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    round_1 = Round(
        tournament_id=tournament.id, seq=1, name="Round 1", stage=RoundStage.PRELIMINARY,
        status=RoundStatus.RELEASED,
    )
    db_session.add(round_1)
    await db_session.flush()
    teams = [
        Team(tournament_id=tournament.id, external_id=200 + i, name=f"Board Team {i}")
        for i in range(4)
    ]
    db_session.add_all(teams)
    await db_session.flush()
    debate_a = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=900)
    debate_b = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=901)
    db_session.add_all([debate_a, debate_b])
    await db_session.flush()
    for debate, pair in ((debate_a, teams[:2]), (debate_b, teams[2:])):
        for team, position in zip(
            pair, (BPPosition.OPENING_GOVERNMENT, BPPosition.OPENING_OPPOSITION), strict=True
        ):
            db_session.add(DebateTeam(debate_id=debate.id, team_id=team.id, position=position))
    await db_session.commit()
    await db_session.refresh(round_1)
    await db_session.refresh(debate_a)
    await db_session.refresh(debate_b)
    return tournament, round_1, debate_a, debate_b, teams


async def test_market_board_round_winner_multi_debate_characterization(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """CHARACTERIZATION test, not a spec: pins market_board's exact current odds output for a
    round_winner market spanning 2 debates with bets on each -- the generic per-payload fallback
    path (see odds_service.market_board) that re-quotes every distinct payload from scratch.
    Any refactor of that path (e.g. fixing its N+1 query pattern) must keep these numbers
    IDENTICAL; if they change, the refactor introduced a behavior difference, not just a
    performance one."""
    tournament, round_1, debate_a, debate_b, teams = await _make_round_with_two_debates(db_session)
    admin = await make_user(db_session, email="admin-board@example.com", role=UserRole.ADMIN)
    alice = await make_user(db_session, email="alice-board@example.com")
    bob = await make_user(db_session, email="bob-board@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "round_winner",
            "label": "Ganador de cada sala",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": round_1.id,
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"debate_id": debate_a.id, "team_id": teams[0].id}, "stake_amount": 30.0},
        headers=auth_headers(alice),
    )
    await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"debate_id": debate_b.id, "team_id": teams[2].id}, "stake_amount": 15.0},
        headers=auth_headers(bob),
    )

    board = await client.get(f"/api/v1/bet-markets/{market_id}/board")
    assert board.status_code == 200
    body = board.json()

    assert body["pool_total"] == 45.0
    assert body["bettors"] == 2
    options_by_label = {o["label"]: o for o in body["options"]}
    assert set(options_by_label) == {"Board Team 0 gana su debate", "Board Team 2 gana su debate"}
    assert options_by_label["Board Team 0 gana su debate"]["stake"] == 30.0
    assert options_by_label["Board Team 0 gana su debate"]["backers"] == 1
    assert options_by_label["Board Team 0 gana su debate"]["odds"] == 1.77
    assert options_by_label["Board Team 2 gana su debate"]["stake"] == 15.0
    assert options_by_label["Board Team 2 gana su debate"]["odds"] == 1.87


async def test_round_head_to_head_quote_place_and_settle_with_sub_bet(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, round_1, debate, teams = await _make_full_call_debate(db_session)
    admin = await make_user(db_session, email="admin-h2h@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user-h2h@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "round_head_to_head",
            "label": "Team 0 vs Team 1",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": round_1.id,
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201
    market_id = create_response.json()["id"]

    base_payload = {
        "debate_id": debate.id, "team_a_id": teams[0].id, "team_b_id": teams[1].id,
        "predicted_higher_id": teams[0].id,
    }

    # Base-only quote: fair 50/50 field (no results yet) -> exactly 2.0x.
    base_quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": base_payload},
        headers=auth_headers(user),
    )
    assert base_quote.status_code == 200
    assert base_quote.json()["odds"] == 2.0
    assert base_quote.json()["sub_bet_odds"] is None  # no sub_bet in payload -> not priced

    # With the rank-gap sub-bet attached, sub_bet_odds is now also priced.
    with_sub_bet = {**base_payload, "sub_bet": {"rank_gap": 2}}
    combo_quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": with_sub_bet},
        headers=auth_headers(user),
    )
    assert combo_quote.status_code == 200
    assert combo_quote.json()["odds"] == 2.0
    assert combo_quote.json()["sub_bet_odds"] > 1.0

    prediction_response = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": with_sub_bet, "stake_amount": 10.0},
        headers=auth_headers(user),
    )
    assert prediction_response.status_code == 201
    body = prediction_response.json()
    assert body["odds"] == 2.0
    assert body["sub_bet_odds"] == combo_quote.json()["sub_bet_odds"]

    # Confirm the ballot: team[0] 1st, team[1] 3rd -> higher (team[0]) wins, gap is exactly 2.
    for team, rank in zip(teams, [1, 3, 2, 4], strict=True):
        row = (
            await db_session.execute(
                select(DebateTeam).where(
                    DebateTeam.debate_id == debate.id, DebateTeam.team_id == team.id
                )
            )
        ).scalar_one()
        row.rank_in_debate = rank
    await db_session.commit()

    settle_response = await client.post(
        f"/api/v1/bet-markets/{market_id}/settle", json={}, headers=auth_headers(admin)
    )
    assert settle_response.status_code == 200
    assert settle_response.json() == {"settled": True}

    after = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(user)
    )
    settled_prediction = after.json()[0]
    assert settled_prediction["status"] == "settled"
    assert settled_prediction["sub_bet_status"] == "settled"
    expected_payout = 10.0 * settled_prediction["odds"] * settled_prediction["sub_bet_odds"]
    assert settled_prediction["points_awarded"] == pytest.approx(expected_payout)
    assert settled_prediction["sub_bet_points_awarded"] == pytest.approx(expected_payout)
