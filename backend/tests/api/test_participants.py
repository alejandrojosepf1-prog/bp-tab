from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Institution, Speaker, Team, Tournament
from app.models.enums import TournamentStatus


async def _make_tournament(db_session: AsyncSession) -> Tournament:
    tournament = Tournament(
        name="Teams Cup",
        slug="teams-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def test_list_teams_is_public_and_includes_nested_institution_and_speakers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)
    institution = Institution(
        tournament_id=tournament.id, code="PUCP", name="Pontificia Universidad Católica"
    )
    db_session.add(institution)
    await db_session.flush()

    team = Team(
        tournament_id=tournament.id,
        external_id=101,
        name="PUCP FM",
        emoji="🦊",
        institution_id=institution.id,
    )
    db_session.add(team)
    await db_session.flush()

    speaker = Speaker(tournament_id=tournament.id, team_id=team.id, name="Jane Doe")
    db_session.add(speaker)
    await db_session.commit()

    response = await client.get(f"/api/v1/tournaments/{tournament.id}/teams")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    team_json = body[0]
    assert team_json["id"] == team.id
    assert team_json["external_id"] == 101
    assert team_json["name"] == "PUCP FM"
    assert team_json["institution"]["code"] == "PUCP"
    assert len(team_json["speakers"]) == 1
    assert team_json["speakers"][0]["name"] == "Jane Doe"
    assert team_json["speakers"][0]["categories"] == []


async def test_get_single_team(client: AsyncClient, db_session: AsyncSession) -> None:
    tournament = await _make_tournament(db_session)
    team = Team(tournament_id=tournament.id, external_id=202, name="Solo Team")
    db_session.add(team)
    await db_session.commit()

    response = await client.get(f"/api/v1/tournaments/{tournament.id}/teams/{team.id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Solo Team"
    assert response.json()["institution"] is None


async def test_get_unknown_team_is_404(client: AsyncClient, db_session: AsyncSession) -> None:
    tournament = await _make_tournament(db_session)
    await db_session.commit()

    response = await client.get(f"/api/v1/tournaments/{tournament.id}/teams/999999")
    assert response.status_code == 404


async def test_list_teams_empty_tournament_returns_empty_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)
    await db_session.commit()

    response = await client.get(f"/api/v1/tournaments/{tournament.id}/teams")
    assert response.status_code == 200
    assert response.json() == []
