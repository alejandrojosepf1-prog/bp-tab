import datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BetMarket, Round, Tournament
from app.models.enums import BetMarketStatus, BetType, RoundStage, RoundStatus, TournamentStatus
from tests.api.conftest import auth_headers, make_user

NOW = datetime.datetime.now(datetime.timezone.utc)


async def test_dashboard_public_without_auth_omits_my_predictions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = Tournament(
        name="Dash Cup",
        slug="dash-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(round_1)
    market = BetMarket(
        tournament_id=tournament.id,
        bet_type=BetType.CHAMPION,
        label="Champion?",
        opens_at=NOW - datetime.timedelta(days=1),
        closes_at=NOW + datetime.timedelta(days=1),
        points_rule={},
        status=BetMarketStatus.OPEN,
    )
    db_session.add(market)
    await db_session.commit()

    response = await client.get(f"/api/v1/tournaments/{tournament.id}/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_round"]["seq"] == 1
    assert body["my_predictions"] is None
    assert len(body["open_bet_markets"]) == 1
    assert body["recent_changes"] == []
    assert body["leaderboard_top"] == []


async def test_dashboard_authenticated_includes_my_predictions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = Tournament(
        name="Dash Cup 2",
        slug="dash-cup-2",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.commit()
    user = await make_user(db_session, email="dashuser@example.com")

    response = await client.get(
        f"/api/v1/tournaments/{tournament.id}/dashboard", headers=auth_headers(user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["my_predictions"] == []
