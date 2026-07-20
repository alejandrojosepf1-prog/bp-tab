import datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, Tournament
from app.models.enums import TournamentStatus, UserRole
from tests.api.conftest import auth_headers, make_user

NOW = datetime.datetime.now(datetime.timezone.utc)
PAST = NOW - datetime.timedelta(days=1)
FUTURE = NOW + datetime.timedelta(days=1)


async def _make_tournament_with_team(db_session: AsyncSession) -> tuple[Tournament, Team, Team]:
    """Two teams, not one: odds pricing needs at least a 2-team field to price anything (a
    lone-candidate market is a nonsensical "certain to win" case), and most of these tests just
    need *a* second, real team for the "wrong pick" side of a bet."""
    tournament = Tournament(
        name="Betting Cup",
        slug="betting-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
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

    # /predictions/me reflects what each user just submitted.
    me_response = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(alice)
    )
    assert me_response.status_code == 200
    assert me_response.json()["payload"] == {"team_id": team.id}

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
    # 0.4 -> decimal odds (1/0.4)/1.07 = 2.34. She staked 100 on the winner, so she's paid
    # stake * odds = 234; Bob staked 50 on the loser and gets nothing back.
    alice_after = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(alice)
    )
    assert alice_after.json()["status"] == "settled"
    assert alice_after.json()["odds"] == 2.34
    assert alice_after.json()["points_awarded"] == 234.0

    bob_after = await client.get(
        f"/api/v1/bet-markets/{market_id}/predictions/me", headers=auth_headers(bob)
    )
    assert bob_after.json()["points_awarded"] == 0.0

    leaderboard_response = await client.get(f"/api/v1/tournaments/{tournament.id}/leaderboard")
    assert leaderboard_response.status_code == 200
    leaderboard = leaderboard_response.json()
    assert len(leaderboard) == 2
    top = leaderboard[0]
    assert top["user"]["display_name"] == "Alice"
    assert top["total_points"] == 134.0  # net profit: 234 payout - 100 stake
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
    alice = await make_user(db_session, email="alice2@example.com", display_name="Alice2")
    bob = await make_user(db_session, email="bob2@example.com", display_name="Bob2")
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

    # Before anyone's bet, the quote is the fair 50/50 prior (2.0 / 1.07 ~= 1.87).
    initial_quote = await client.post(
        f"/api/v1/bet-markets/{market_id}/quote",
        json={"payload": {"team_id": team.id}},
        headers=auth_headers(carol),
    )
    assert initial_quote.json()["odds"] == 1.87

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
    assert team_quote.json()["odds"] < 1.87
    assert other_team_quote.json()["odds"] > 1.87
