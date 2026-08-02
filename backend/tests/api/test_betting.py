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
    MotionCategory,
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

    # Alice predicts correctly, Bob predicts incorrectly. Stakes at MAX_STAKE (50.0, Pieza 3's
    # per-bet cap).
    alice_prediction = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 50.0},
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
        json={"payload": {"team_id": team.id}, "stake_amount": 50.0},
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
    # (power=0 for both) -- see app.domain.odds's pari-mutuel-with-seed model. Alice's `odds`
    # field is the LOCKED-IN quote from her final (resubmit) call, computed EXCLUDING her own
    # stake (odds_service._open_stakes's exclude_user_id) -- at that moment the pool she was
    # priced against was just Bob's 50 on the OTHER team: pari_mutuel_probability(0, 50, 0.5,
    # seed=200) = 100/250 = 0.4 -> decimal odds 2.5.
    #
    # Pieza 3: that quote is now only ever a placement-time PROJECTION, never what settlement
    # actually pays -- settlement_payout_ratio recomputes the SAME formula against the pool's
    # TRUE final composition (everyone's stakes, hers included): candidate=50 (her own stake,
    # MAX_STAKE), pool=100 (50+50). pari_mutuel_probability(50, 100, 0.5, seed=200) = 150/300 =
    # 0.5 -> decimal odds 2.0 exactly (a perfectly symmetric pool matches the flat fair price).
    # She staked 50 on the winner, so she's paid stake * 2.0 = 100; Bob staked 50 on the loser
    # and gets nothing back.
    alice_after = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(alice)
    )
    assert alice_after.json()[0]["status"] == "settled"
    assert alice_after.json()[0]["odds"] == 2.5  # placement-time projection, unchanged
    assert alice_after.json()[0]["points_awarded"] == 100.0  # actual pari-mutuel payout

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
    assert top["total_points"] == 50.0  # net profit: 100 payout - 50 stake
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
    # Three separate backers at MAX_STAKE (50.0, Pieza 3's per-bet cap) rather than two heavy
    # single stakes -- combined 150 still overwhelms the 200-token seed the same way the
    # original two-account 150-each setup did; the point (real money piling onto one side moves
    # the price) doesn't depend on how many accounts that money came from.
    alice = await make_user(
        db_session, email="alice2@example.com", display_name="Alice2", balance=1000.0
    )
    bob = await make_user(
        db_session, email="bob2@example.com", display_name="Bob2", balance=1000.0
    )
    dave = await make_user(
        db_session, email="dave2@example.com", display_name="Dave2", balance=1000.0
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

    # Alice, Bob, and Dave all back `team` at the max per-bet stake -- their combined stake (150)
    # starts to dominate the 200-seed, so the crowd's conviction should shorten `team`'s price
    # below the prior...
    for backer in (alice, bob, dave):
        response = await client.post(
            f"/api/v1/bet-markets/{market_id}/predictions",
            json={"payload": {"team_id": team.id}, "stake_amount": 50.0},
            headers=auth_headers(backer),
        )
        assert response.status_code == 201

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


async def test_odds_history_captures_and_serves_snapshots(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """capture_odds_snapshot (called once per autoscrape cycle in production, see
    app.tasks.autoscrape) writes one row per option; the history endpoint serves them back
    scoped to this market and ordered by time. A market with no captures yet returns an empty
    list rather than erroring."""
    tournament, team, _other_team = await _make_tournament_with_team(db_session)
    admin = await make_user(db_session, email="admin-history@example.com", role=UserRole.ADMIN)
    alice = await make_user(db_session, email="alice-history@example.com")

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

    empty_history = await client.get(f"/api/v1/bet-markets/{market_id}/odds-history")
    assert empty_history.json()["points"] == []

    await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 10.0},
        headers=auth_headers(alice),
    )

    from app.services.odds_service import capture_odds_snapshot

    written = await capture_odds_snapshot(db_session, tournament.id)
    await db_session.commit()
    assert written > 0

    history = await client.get(f"/api/v1/bet-markets/{market_id}/odds-history")
    points = history.json()["points"]
    assert points
    assert any(p["option_key"] == f"team:{team.id}" for p in points)


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

    # Position 4 is now IN range (the "Tabla de oradores" market goes to 10, priced via
    # simulation past position 3 -- see odds_service.MAX_SPEAKER_POSITION), so it must quote
    # cleanly instead of rejecting.
    deep_position = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"speaker_id": speaker_a.id, "position": 4}},
        headers=auth_headers(user),
    )
    assert deep_position.status_code == 200

    invalid_position = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"speaker_id": speaker_a.id, "position": 11}},
        headers=auth_headers(user),
    )
    assert invalid_position.status_code == 422


async def test_top_speaker_position_prices_from_team_points_when_scores_are_withheld(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression for the live pricing bug: CMUDE (like most tabs) withholds EVERY speaker score
    until the tournament ends, so the old SpeakerScore-only power rating left every speaker at
    0.0, softmax returned a flat 1/N over the field, and every single quote clamped to MAX_ODDS
    -- the whole market paid a uniform 50x on every speaker at every position. Verified against
    production: 107 teams, all reporting total_speaker_points 0.0 after nine judged rounds.

    With zero speaker scores present, team_points must still separate a strong team's speaker
    from a weak team's, and no quote may sit at MAX_ODDS.
    """
    tournament, _team, _other = await _make_tournament_with_team(db_session)
    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(round_1)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=910)
    db_session.add(debate)
    await db_session.flush()

    # Four teams ranked 1st-4th in one judged debate -> team_points 3/2/1/0, and deliberately NOT
    # a single SpeakerScore row anywhere: exactly the production shape.
    speakers = []
    for i, position in enumerate(
        [
            BPPosition.OPENING_GOVERNMENT,
            BPPosition.OPENING_OPPOSITION,
            BPPosition.CLOSING_GOVERNMENT,
            BPPosition.CLOSING_OPPOSITION,
        ]
    ):
        team = Team(tournament_id=tournament.id, external_id=900 + i, name=f"Tab Team {i}")
        db_session.add(team)
        await db_session.flush()
        db_session.add(
            DebateTeam(
                debate_id=debate.id,
                team_id=team.id,
                position=position,
                rank_in_debate=i + 1,
            )
        )
        speaker = Speaker(tournament_id=tournament.id, team_id=team.id, name=f"Tab Speaker {i}")
        db_session.add(speaker)
        speakers.append(speaker)
    await db_session.commit()
    for speaker in speakers:
        await db_session.refresh(speaker)

    admin = await make_user(db_session, email="admin-tab@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user-tab@example.com")
    user_headers = auth_headers(user)

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
    market_id = create_response.json()["id"]

    async def quote(speaker_id: int, position: int) -> float:
        response = await client.post(
            f"/api/v1/bet-markets/{market_id}/quote",
            json={"payload": {"speaker_id": speaker_id, "position": position}},
            headers=user_headers,
        )
        assert response.status_code == 200
        return response.json()["odds"]

    winner_first = await quote(speakers[0].id, 1)
    loser_first = await quote(speakers[3].id, 1)

    # The bug in one assertion: these used to be identical, and identically MAX_ODDS.
    assert winner_first < loser_first
    assert winner_first < 50.0
    assert loser_first < 50.0

    # Deeper slots pay more than shallow ones for the SAME speaker (more plausible occupants the
    # further down the tab you go) -- the fixed base-per-position component.
    assert await quote(speakers[0].id, 10) > await quote(speakers[0].id, 1)


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


async def _seed_positional_history_favoring_og(db_session: AsyncSession) -> None:
    """Populates PRELIMINARY-round debate history (in an unrelated tournament -- see
    positional_stats_service, which counts across every tournament in the database) where
    Opening Government always wins and Opening Opposition never does. Used to prove
    round_winner pricing actually picks this up end-to-end, not just at the domain-function
    level (see test_apply_positional_adjustment_favors_the_historically_stronger_position in
    tests/domain/test_odds.py for that lower-level check)."""
    tournament = Tournament(
        name="Positional History Source",
        slug="positional-history-source",
        source_base_url="https://positional-history.calicotab.com",
        source_slug="open",
        status=TournamentStatus.COMPLETED,
    )
    db_session.add(tournament)
    await db_session.flush()
    round_ = Round(
        tournament_id=tournament.id, seq=1, name="Round 1", stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(round_)
    await db_session.flush()
    for i in range(5):
        og_team = Team(tournament_id=tournament.id, external_id=1000 + i * 2, name=f"OG Winner {i}")
        oo_team = Team(tournament_id=tournament.id, external_id=1001 + i * 2, name=f"OO Loser {i}")
        db_session.add_all([og_team, oo_team])
        await db_session.flush()
        debate = Debate(tournament_id=tournament.id, round_id=round_.id, external_id=2000 + i)
        db_session.add(debate)
        await db_session.flush()
        db_session.add_all(
            [
                DebateTeam(
                    debate_id=debate.id,
                    team_id=og_team.id,
                    position=BPPosition.OPENING_GOVERNMENT,
                    rank_in_debate=1,
                ),
                DebateTeam(
                    debate_id=debate.id,
                    team_id=oo_team.id,
                    position=BPPosition.OPENING_OPPOSITION,
                    rank_in_debate=4,
                ),
            ]
        )
    await db_session.commit()


async def test_round_winner_quote_reflects_positional_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """End-to-end proof that CNADE Roadmap Pieza 2b's positional prior actually reaches live
    pricing: two teams with IDENTICAL power (both zero debates played) in a fresh debate should
    price as a coin toss with no history, but once Opening Government has a real, seeded
    historical edge over Opening Opposition, quote_odds must reflect it."""
    await _seed_positional_history_favoring_og(db_session)

    tournament, _t1, _t2 = await _make_tournament_with_team(db_session)
    round_ = Round(
        tournament_id=tournament.id, seq=1, name="Round 1", stage=RoundStage.PRELIMINARY,
        status=RoundStatus.RELEASED,
    )
    db_session.add(round_)
    await db_session.flush()
    og_team = Team(tournament_id=tournament.id, external_id=500, name="Fresh OG")
    oo_team = Team(tournament_id=tournament.id, external_id=501, name="Fresh OO")
    db_session.add_all([og_team, oo_team])
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_.id, external_id=999)
    db_session.add(debate)
    await db_session.flush()
    db_session.add_all(
        [
            DebateTeam(debate_id=debate.id, team_id=og_team.id, position=BPPosition.OPENING_GOVERNMENT),
            DebateTeam(debate_id=debate.id, team_id=oo_team.id, position=BPPosition.OPENING_OPPOSITION),
        ]
    )
    await db_session.commit()

    admin = await make_user(db_session, email="admin-pos@example.com", role=UserRole.ADMIN)
    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "round_winner",
            "label": "Ganador",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": round_.id,
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    og_quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"debate_id": debate.id, "team_id": og_team.id}},
        headers=auth_headers(admin),
    )
    oo_quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"debate_id": debate.id, "team_id": oo_team.id}},
        headers=auth_headers(admin),
    )

    assert og_quote.status_code == 200
    assert oo_quote.status_code == 200
    # Lower decimal odds = higher implied probability -- OG should be the priced favorite.
    assert og_quote.json()["odds"] < oo_quote.json()["odds"]


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
    # Pieza 3: `odds` is only the placement-time projection now, not what settlement actually
    # pays -- `stake * odds * sub_bet_odds` no longer predicts the real payout, since the base
    # portion is the pari-mutuel ratio computed from the pool's final composition instead.
    assert settled_prediction["points_awarded"] == pytest.approx(37.8)
    assert settled_prediction["sub_bet_points_awarded"] == pytest.approx(37.8)


async def test_round_winner_speaker_points_sub_bet_pays_base_immediately_and_stays_open(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Unlike round_head_to_head/team_break's all-or-nothing combo above, round_winner's
    speaker-points sub-bet settles in TWO separate steps: /settle only ever resolves the base
    pick here (speaker points are frequently withheld until the tournament's final tab) -- the
    sub-bet itself only resolves later via `betting_service.settle_pending_sub_bets`, run from
    the auto-scrape cycle rather than any HTTP endpoint, so that half is exercised directly at
    the service layer (see test_betting_service.py) rather than through this client."""
    tournament, round_1, debate, teams = await _make_full_call_debate(db_session)
    winning_team = teams[0]
    speakers = [
        Speaker(tournament_id=tournament.id, team_id=winning_team.id, name=f"Speaker {i}")
        for i in (1, 2)
    ]
    db_session.add_all(speakers)
    await db_session.commit()

    admin = await make_user(db_session, email="admin-rw@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user-rw@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "round_winner",
            "label": "Round 1 winners",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": round_1.id,
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201
    market_id = create_response.json()["id"]

    payload = {
        "debate_id": debate.id,
        "team_id": winning_team.id,
        "sub_bet": {
            "speaker_scores": [
                {"speaker_id": speakers[0].id, "points": 76.0},
                {"speaker_id": speakers[1].id, "points": 75.5},
            ]
        },
    }
    quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": payload},
        headers=auth_headers(user),
    )
    assert quote.status_code == 200
    assert quote.json()["sub_bet_odds"] == 15.0

    prediction_response = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": payload, "stake_amount": 10.0},
        headers=auth_headers(user),
    )
    assert prediction_response.status_code == 201

    for team, rank in zip(teams, [1, 2, 3, 4], strict=True):
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
    # Pieza 3: `odds` is only the placement-time projection, not what settlement pays -- the
    # base is now the pari-mutuel ratio computed from the pool's final composition.
    assert settled_prediction["points_awarded"] == pytest.approx(16.0)
    # The base pick already paid in full -- the sub-bet is still awaiting real speaker points.
    assert settled_prediction["sub_bet_status"] == "open"
    assert settled_prediction["sub_bet_points_awarded"] is None


async def test_round_winner_speaker_order_sub_bet_settles_same_time_as_base(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Unlike speaker_scores above, round_winner's OTHER modifier -- speaker_order, "who opens
    this team's bench" -- is known the instant the round is judged (SpeakerRole, unlike a raw
    score, is never withheld), so it settles in the SAME /settle call as the base pick, not
    later via settle_pending_sub_bets."""
    tournament, round_1, debate, teams = await _make_full_call_debate(db_session)
    winning_team = teams[0]
    winning_debate_team = (
        await db_session.execute(
            select(DebateTeam).where(
                DebateTeam.debate_id == debate.id, DebateTeam.team_id == winning_team.id
            )
        )
    ).scalar_one()
    speakers = [
        Speaker(tournament_id=tournament.id, team_id=winning_team.id, name=f"Speaker {i}")
        for i in (1, 2)
    ]
    db_session.add_all(speakers)
    await db_session.flush()
    db_session.add_all(
        [
            SpeakerScore(
                debate_team_id=winning_debate_team.id,
                speaker_id=speakers[0].id,
                role=SpeakerRole.PM,
                score=76.0,
            ),
            SpeakerScore(
                debate_team_id=winning_debate_team.id,
                speaker_id=speakers[1].id,
                role=SpeakerRole.DPM,
                score=75.0,
            ),
        ]
    )
    await db_session.commit()

    admin = await make_user(db_session, email="admin-rwo@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user-rwo@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "round_winner",
            "label": "Round 1 winners",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": round_1.id,
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    payload = {
        "debate_id": debate.id,
        "team_id": winning_team.id,
        "sub_bet": {"speaker_order": {"speaker_id": speakers[0].id, "position": 1}},
    }
    quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": payload},
        headers=auth_headers(user),
    )
    assert quote.status_code == 200
    assert quote.json()["sub_bet_odds"] == 2.0

    prediction_response = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": payload, "stake_amount": 10.0},
        headers=auth_headers(user),
    )
    assert prediction_response.status_code == 201

    for team, rank in zip(teams, [1, 2, 3, 4], strict=True):
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
    # Both the base pick (team won) and the sub-bet (speakers[0] really was PM, position 1)
    # are correct -- and, unlike the deferred speaker_scores test above, this resolves in the
    # SAME settle call: sub_bet_status is already "settled", not left "open".
    assert settled_prediction["status"] == "settled"
    assert settled_prediction["sub_bet_status"] == "settled"
    # Pieza 3: `odds` is only the placement-time projection -- `stake * odds * sub_bet_odds` no
    # longer predicts the real payout, since the base portion is the pari-mutuel ratio computed
    # from the pool's final composition instead.
    assert settled_prediction["points_awarded"] == pytest.approx(32.0)
    assert settled_prediction["sub_bet_points_awarded"] == pytest.approx(32.0)


async def test_motion_type_fixed_odds_min_stake_and_premature_settlement_guard(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """MOTION_TYPE is the one bet type priced outside pari-mutuel: fixed 5x regardless of stake,
    a minimum stake per pick, and settlement gated on BOTH the admin-loaded ground truth AND the
    motion actually being revealed (motion_text) -- loading the category alone must never let
    the very next settle call pay out before debaters even see the motion."""
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.RELEASED,
    )
    db_session.add(round_1)
    await db_session.commit()
    await db_session.refresh(round_1)

    admin = await make_user(db_session, email="admin-motion@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user-motion@example.com")
    # Captured once: a 422 response rolls back the app's own session, which expires these ORM
    # objects -- re-touching `user.id`/`admin.id` afterward (as auth_headers does) then fails
    # with MissingGreenlet outside the request's own async context. Reusing the same headers
    # dicts sidesteps that entirely.
    admin_headers = auth_headers(admin)
    user_headers = auth_headers(user)

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "motion_type",
            "label": "Tipo de moción Ronda 1",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": round_1.id,
        },
        headers=admin_headers,
    )
    assert create_response.status_code == 201
    market_id = create_response.json()["id"]

    # Fixed odds: always 5.0x, no pool blending, before or after other stakes exist.
    quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"category": "policy"}},
        headers=user_headers,
    )
    assert quote.status_code == 200
    assert quote.json()["odds"] == 5.0

    # Anti-exploit: a stake under the minimum is rejected outright.
    too_small = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"category": "policy"}, "stake_amount": 5.0},
        headers=user_headers,
    )
    assert too_small.status_code == 422

    prediction_response = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"category": "policy"}, "stake_amount": 20.0},
        headers=user_headers,
    )
    assert prediction_response.status_code == 201
    assert prediction_response.json()["odds"] == 5.0

    # Neither settling with no ground truth loaded, nor with it loaded but the motion still
    # unrevealed (motion_text still null), is allowed to pay out.
    settle_before = await client.post(
        f"/api/v1/bet-markets/{market_id}/settle", json={}, headers=admin_headers
    )
    assert settle_before.json() == {"settled": False}

    load_answer = await client.patch(
        f"/api/v1/admin/rounds/{round_1.id}/motion-category",
        json={"motion_category": "policy"},
        headers=admin_headers,
    )
    assert load_answer.status_code == 200
    assert load_answer.json()["motion_category"] == "policy"

    settle_before_reveal = await client.post(
        f"/api/v1/bet-markets/{market_id}/settle", json={}, headers=admin_headers
    )
    assert settle_before_reveal.json() == {
        "settled": False
    }  # ground truth loaded, but motion not yet revealed

    round_1.motion_text = "Esta Casa prohibiría la publicidad dirigida a menores de edad"
    await db_session.commit()

    settle_after_reveal = await client.post(
        f"/api/v1/bet-markets/{market_id}/settle", json={}, headers=admin_headers
    )
    assert settle_after_reveal.json() == {"settled": True}

    after = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=user_headers
    )
    settled_prediction = after.json()[0]
    assert settled_prediction["status"] == "settled"
    assert settled_prediction["points_awarded"] == pytest.approx(20.0 * 5.0)


async def test_motion_type_wrong_category_loses(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, _team, _other_team = await _make_tournament_with_team(db_session)
    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.RELEASED,
        motion_category=MotionCategory.REGRET,
        motion_text="Esta Casa lamenta el auge de la cultura del sexo casual",
    )
    db_session.add(round_1)
    await db_session.commit()
    await db_session.refresh(round_1)

    admin = await make_user(db_session, email="admin-motion2@example.com", role=UserRole.ADMIN)
    user = await make_user(db_session, email="user-motion2@example.com")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "motion_type",
            "label": "Tipo de moción Ronda 1",
            "opens_at": PAST.isoformat(),
            "closes_at": FUTURE.isoformat(),
            "target_round_id": round_1.id,
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"category": "policy"}, "stake_amount": 20.0},
        headers=auth_headers(user),
    )

    settle_response = await client.post(
        f"/api/v1/bet-markets/{market_id}/settle", json={}, headers=auth_headers(admin)
    )
    assert settle_response.json() == {"settled": True}

    after = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(user)
    )
    settled_prediction = after.json()[0]
    assert settled_prediction["status"] == "settled"
    assert settled_prediction["points_awarded"] == 0.0
