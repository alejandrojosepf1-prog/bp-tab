from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from tests.api.conftest import auth_headers, make_user


async def test_list_users_requires_admin(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session, email="plain@example.com", role=UserRole.USER)

    response = await client.get("/api/v1/admin/users", headers=auth_headers(user))
    assert response.status_code == 403


async def test_list_users_unauthenticated_is_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 401


async def test_list_users_as_admin(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await make_user(db_session, email="root@example.com", role=UserRole.ADMIN)
    await make_user(db_session, email="member@example.com", role=UserRole.USER)

    response = await client.get("/api/v1/admin/users", headers=auth_headers(admin))
    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert {"root@example.com", "member@example.com"} <= emails


async def test_admin_can_promote_user_and_deactivate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await make_user(db_session, email="root2@example.com", role=UserRole.ADMIN)
    member = await make_user(db_session, email="member2@example.com", role=UserRole.USER)

    response = await client.patch(
        f"/api/v1/admin/users/{member.id}",
        json={"role": "admin", "is_active": False},
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["is_active"] is False


async def test_scrape_logs_requires_admin(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session, email="notadmin2@example.com", role=UserRole.USER)

    response = await client.get("/api/v1/admin/scrape-logs", headers=auth_headers(user))
    assert response.status_code == 403
