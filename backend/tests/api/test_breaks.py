from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BreakCategory, Tournament
from app.models.enums import TournamentStatus, UserRole
from tests.api.conftest import auth_headers, make_user


async def _make_tournament_with_category(
    db_session: AsyncSession, *, break_size: int | None = None, slug: str = "break-cup"
) -> tuple[Tournament, BreakCategory]:
    tournament = Tournament(
        name="Break Cup",
        slug=slug,
        source_base_url="https://example.calicotab.com",
        source_slug=slug,
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    category = BreakCategory(
        tournament_id=tournament.id, name="Open", slug="open", is_general=True,
        break_size=break_size,
    )
    db_session.add(category)
    await db_session.commit()
    await db_session.refresh(tournament)
    await db_session.refresh(category)
    return tournament, category


async def test_update_break_category_requires_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, category = await _make_tournament_with_category(db_session)
    user = await make_user(db_session, email="user@example.com", role=UserRole.USER)

    response = await client.patch(
        f"/api/v1/tournaments/{tournament.id}/break-categories/{category.id}",
        json={"break_size": 16},
        headers=auth_headers(user),
    )
    assert response.status_code == 403


async def test_update_break_category_sets_break_size(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, category = await _make_tournament_with_category(db_session, break_size=None)
    admin = await make_user(db_session, email="admin@example.com", role=UserRole.ADMIN)

    response = await client.patch(
        f"/api/v1/tournaments/{tournament.id}/break-categories/{category.id}",
        json={"break_size": 32},
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["break_size"] == 32

    listed = await client.get(f"/api/v1/tournaments/{tournament.id}/break-categories")
    assert listed.json()[0]["break_size"] == 32


async def test_update_break_category_rejects_non_positive_size(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament, category = await _make_tournament_with_category(db_session)
    admin = await make_user(db_session, email="admin2@example.com", role=UserRole.ADMIN)

    response = await client.patch(
        f"/api/v1/tournaments/{tournament.id}/break-categories/{category.id}",
        json={"break_size": 0},
        headers=auth_headers(admin),
    )
    assert response.status_code == 422


async def test_update_break_category_404_for_wrong_tournament(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _tournament, category = await _make_tournament_with_category(db_session, slug="break-cup-a")
    other_tournament, _ = await _make_tournament_with_category(db_session, slug="break-cup-b")
    admin = await make_user(db_session, email="admin3@example.com", role=UserRole.ADMIN)

    response = await client.patch(
        f"/api/v1/tournaments/{other_tournament.id}/break-categories/{category.id}",
        json={"break_size": 8},
        headers=auth_headers(admin),
    )
    assert response.status_code == 404
