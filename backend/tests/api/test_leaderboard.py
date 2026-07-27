import datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, Tournament
from app.models.enums import TournamentStatus, UserRole
from tests.api.conftest import auth_headers, make_user

NOW = datetime.datetime.now(datetime.timezone.utc)
PAST = NOW - datetime.timedelta(days=1)
FUTURE = NOW + datetime.timedelta(days=1)


async def test_global_leaderboard_empty_with_no_settled_predictions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await make_user(db_session, email="nobody@example.com")

    response = await client.get("/api/v1/leaderboard/global")

    assert response.status_code == 200
    assert response.json() == []


async def test_global_leaderboard_ranks_across_tournaments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = Tournament(
        name="Ranking Cup", slug="ranking-cup", source_base_url="https://example.calicotab.com",
        source_slug="open", status=TournamentStatus.UPCOMING,
    )
    db_session.add(tournament)
    await db_session.flush()
    team = Team(tournament_id=tournament.id, external_id=1, name="Winners")
    other_team = Team(tournament_id=tournament.id, external_id=2, name="Losers")
    db_session.add_all([team, other_team])
    await db_session.commit()
    await db_session.refresh(tournament)

    admin = await make_user(db_session, email="admin-rank@example.com", role=UserRole.ADMIN)
    alice = await make_user(db_session, email="alice-rank@example.com", display_name="AliceRank")

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion", "label": "Champ",
            "opens_at": PAST.isoformat(), "closes_at": FUTURE.isoformat(),
        },
        headers=auth_headers(admin),
    )
    market_id = create_response.json()["id"]

    await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 10.0},
        headers=auth_headers(alice),
    )

    tournament_row = await db_session.get(Tournament, tournament.id)
    tournament_row.champion_team_id = team.id
    await db_session.commit()

    settle = await client.post(
        f"/api/v1/bet-markets/{market_id}/settle", json={}, headers=auth_headers(admin)
    )
    assert settle.json() == {"settled": True}

    response = await client.get("/api/v1/leaderboard/global")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["user"]["display_name"] == "AliceRank"
    assert body[0]["rank"] == 1
    assert body[0]["tournaments_played"] == 1
    assert body[0]["total_points"] > 0
