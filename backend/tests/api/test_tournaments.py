import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tournament
from app.models.enums import TournamentStatus, UserRole
from tests.api.conftest import auth_headers, make_user


async def _make_tournament(db_session: AsyncSession, **kwargs) -> Tournament:
    tournament = Tournament(
        name="CMUDE 2025",
        slug="cmude-2025",
        source_base_url="https://cmude2025.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
        **kwargs,
    )
    db_session.add(tournament)
    await db_session.commit()
    await db_session.refresh(tournament)
    return tournament


async def test_list_tournaments_is_public(client: AsyncClient, db_session: AsyncSession) -> None:
    await _make_tournament(db_session)

    response = await client.get("/api/v1/tournaments")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "CMUDE 2025"
    assert body[0]["slug"] == "cmude-2025"


async def test_get_tournament_by_id_is_public(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)

    response = await client.get(f"/api/v1/tournaments/{tournament.id}")
    assert response.status_code == 200
    assert response.json()["id"] == tournament.id


async def test_get_unknown_tournament_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tournaments/999999")
    assert response.status_code == 404


async def test_create_tournament_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tournaments",
        json={
            "name": "New Cup",
            "source_base_url": "https://example.com",
            "source_slug": "open",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 401


async def test_create_tournament_forbidden_for_non_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session, email="user@example.com", role=UserRole.USER)

    response = await client.post(
        "/api/v1/tournaments",
        json={
            "name": "New Cup",
            "source_base_url": "https://example.com",
            "source_slug": "open",
            "timezone": "UTC",
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 403


async def test_create_tournament_as_admin_derives_slug(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await make_user(db_session, email="admin@example.com", role=UserRole.ADMIN)

    response = await client.post(
        "/api/v1/tournaments",
        json={
            "name": "My Great Cup!",
            "source_base_url": "https://example.calicotab.com",
            "source_slug": "open",
            "timezone": "America/Lima",
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "my-great-cup"
    assert body["status"] == "upcoming"
    assert body["is_active"] is True


async def test_patch_tournament_as_admin(client: AsyncClient, db_session: AsyncSession) -> None:
    tournament = await _make_tournament(db_session)
    admin = await make_user(db_session, email="admin2@example.com", role=UserRole.ADMIN)

    response = await client.patch(
        f"/api/v1/tournaments/{tournament.id}",
        json={"is_active": False},
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_patch_tournament_forbidden_for_non_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)
    user = await make_user(db_session, email="user2@example.com", role=UserRole.USER)

    response = await client.patch(
        f"/api/v1/tournaments/{tournament.id}",
        json={"is_active": False},
        headers=auth_headers(user),
    )
    assert response.status_code == 403


async def test_scrape_endpoint_queues_background_task(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Doesn't let the real `scrape_tournament_async` run in the background -- it defaults to
    the real Postgres-backed `AsyncSessionLocal`, which isn't reachable in this in-memory-SQLite
    test environment, and Starlette re-raises a background-task exception after the response has
    already been sent. Patching confirms the endpoint schedules the right call without needing a
    live database for the scrape itself."""
    tournament = await _make_tournament(db_session)
    admin = await make_user(db_session, email="admin3@example.com", role=UserRole.ADMIN)

    called = {}

    async def fake_scrape_tournament_async(tournament_id: int, **kwargs: object) -> dict:
        called["tournament_id"] = tournament_id
        return {"tournament_id": tournament_id}

    monkeypatch.setattr(
        "app.api.routers.tournaments.scrape_tournament_async", fake_scrape_tournament_async
    )

    response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/scrape", headers=auth_headers(admin)
    )
    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert called["tournament_id"] == tournament.id


async def test_scrape_endpoint_requires_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)
    user = await make_user(db_session, email="user3@example.com", role=UserRole.USER)

    response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/scrape", headers=auth_headers(user)
    )
    assert response.status_code == 403
