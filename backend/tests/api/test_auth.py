from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.conftest import auth_headers, make_user


async def test_register_creates_user_with_default_role(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "hunter2", "display_name": "Alice"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["display_name"] == "Alice"
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body


async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    payload = {"email": "bob@example.com", "password": "hunter2", "display_name": "Bob"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


async def test_login_success_returns_bearer_token(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "hunter2", "display_name": "Carol"},
    )

    response = await client.post(
        "/api/v1/auth/login", json={"email": "carol@example.com", "password": "hunter2"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


async def test_login_wrong_password_is_unauthorized(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "dave@example.com", "password": "hunter2", "display_name": "Dave"},
    )

    response = await client.post(
        "/api/v1/auth/login", json={"email": "dave@example.com", "password": "wrong"}
    )
    assert response.status_code == 401


async def test_login_unknown_email_is_unauthorized(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert response.status_code == 401


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_me_returns_current_user(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session, email="erin@example.com", display_name="Erin")

    response = await client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == user.id
    assert body["email"] == "erin@example.com"


async def test_me_rejects_inactive_user(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session, email="frank@example.com", is_active=False)

    response = await client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert response.status_code == 401
