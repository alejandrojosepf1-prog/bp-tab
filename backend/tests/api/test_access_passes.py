from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import Speaker
from app.models.enums import UserRole
from app.services.access_pass_service import ACTIVATION_TOKEN_PURPOSE
from tests.api.conftest import auth_headers, make_tournament, make_user


async def test_public_submit_then_admin_lists_and_approves(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await make_tournament(db_session)
    admin = await make_user(db_session, email="admin@example.com", role=UserRole.ADMIN)
    tournament_id = tournament.id

    submit = await client.post(
        f"/api/v1/tournaments/{tournament_id}/access-passes",
        json={"email": "new@example.com", "phone": "+507 6000-0000", "full_name": "Nueva Persona"},
    )
    assert submit.status_code == 201
    body = submit.json()
    assert body["status"] == "pending"
    assert body["match_hint"] is None

    listing = await client.get(
        f"/api/v1/admin/access-passes?tournament_id={tournament_id}",
        headers=auth_headers(admin),
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    pass_id = listing.json()[0]["id"]

    approve = await client.post(
        f"/api/v1/admin/access-passes/{pass_id}/approve", headers=auth_headers(admin)
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"
    assert approve.json()["user_id"] is not None


async def test_non_admin_cannot_list_or_approve(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await make_tournament(db_session)
    user = await make_user(db_session, email="user@example.com")
    tournament_id = tournament.id

    submit = await client.post(
        f"/api/v1/tournaments/{tournament_id}/access-passes",
        json={"email": "a@example.com", "phone": "1", "full_name": "A A"},
    )
    pass_id = submit.json()["id"]

    listing = await client.get(
        f"/api/v1/admin/access-passes?tournament_id={tournament_id}", headers=auth_headers(user)
    )
    assert listing.status_code == 403

    approve = await client.post(
        f"/api/v1/admin/access-passes/{pass_id}/approve", headers=auth_headers(user)
    )
    assert approve.status_code == 403


async def test_reject_then_activate_fails(client: AsyncClient, db_session: AsyncSession) -> None:
    tournament = await make_tournament(db_session)
    admin = await make_user(db_session, email="admin2@example.com", role=UserRole.ADMIN)
    tournament_id = tournament.id
    admin_headers = auth_headers(admin)

    submit = await client.post(
        f"/api/v1/tournaments/{tournament_id}/access-passes",
        json={"email": "a@example.com", "phone": "1", "full_name": "A A"},
    )
    pass_id = submit.json()["id"]

    reject = await client.post(
        f"/api/v1/admin/access-passes/{pass_id}/reject", headers=admin_headers
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    # A forged activation token for this (never-approved) pass must not work.
    token = create_access_token(str(pass_id), extra_claims={"purpose": ACTIVATION_TOKEN_PURPOSE})
    activate = await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "a-real-password"}
    )
    assert activate.status_code == 400


async def test_full_flow_activate_logs_the_user_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await make_tournament(db_session)
    admin = await make_user(db_session, email="admin3@example.com", role=UserRole.ADMIN)
    tournament_id = tournament.id
    admin_headers = auth_headers(admin)

    submit = await client.post(
        f"/api/v1/tournaments/{tournament_id}/access-passes",
        json={"email": "brand-new@example.com", "phone": "1", "full_name": "Brand New"},
    )
    pass_id = submit.json()["id"]
    approve = await client.post(
        f"/api/v1/admin/access-passes/{pass_id}/approve", headers=admin_headers
    )
    assert approve.status_code == 200

    # No Resend key configured in tests -- email_service logs instead of sending, so the only
    # way to get the real token here is to mint one identical to what approve_access_pass did.
    token = create_access_token(str(pass_id), extra_claims={"purpose": ACTIVATION_TOKEN_PURPOSE})
    activate = await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "a-real-password"}
    )
    assert activate.status_code == 200
    assert activate.json()["token_type"] == "bearer"

    # The returned token logs straight in as the new account.
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {activate.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "brand-new@example.com"


async def test_place_prediction_blocked_without_a_pass_when_tournament_requires_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await make_tournament(db_session, requires_access_pass=True)
    user = await make_user(db_session, email="u@example.com")

    market = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Campeón",
            "opens_at": "2020-01-01T00:00:00Z",
            "closes_at": "2099-01-01T00:00:00Z",
        },
        headers=auth_headers(
            await make_user(db_session, email="admin4@example.com", role=UserRole.ADMIN)
        ),
    )
    market_id = market.json()["id"]

    bet = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": 1}, "stake_amount": 10.0},
        headers=auth_headers(user),
    )
    assert bet.status_code == 403


async def test_place_prediction_blocked_for_a_matched_participant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await make_tournament(db_session, requires_access_pass=True)
    admin = await make_user(db_session, email="admin5@example.com", role=UserRole.ADMIN)
    db_session.add(Speaker(tournament_id=tournament.id, name="Compite Aca"))
    await db_session.commit()

    submit = await client.post(
        f"/api/v1/tournaments/{tournament.id}/access-passes",
        json={"email": "compite@example.com", "phone": "1", "full_name": "Compite Aca"},
    )
    pass_id = submit.json()["id"]
    await client.post(f"/api/v1/admin/access-passes/{pass_id}/approve", headers=auth_headers(admin))

    approved_pass = await client.get(
        f"/api/v1/admin/access-passes?tournament_id={tournament.id}", headers=auth_headers(admin)
    )
    user_id = approved_pass.json()[0]["user_id"]
    from app.models import User

    participant_user = await db_session.get(User, user_id)
    participant_headers = auth_headers(participant_user)

    market = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Campeón",
            "opens_at": "2020-01-01T00:00:00Z",
            "closes_at": "2099-01-01T00:00:00Z",
        },
        headers=auth_headers(admin),
    )
    market_id = market.json()["id"]

    bet = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": 1}, "stake_amount": 10.0},
        headers=participant_headers,
    )
    assert bet.status_code == 403


async def test_admin_bypasses_the_access_pass_gate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import Team

    tournament = await make_tournament(db_session, requires_access_pass=True)
    admin = await make_user(db_session, email="admin6@example.com", role=UserRole.ADMIN)
    admin_headers = auth_headers(admin)
    team = Team(tournament_id=tournament.id, external_id=1, name="Equipo Admin")
    db_session.add(team)
    await db_session.commit()

    market = await client.post(
        f"/api/v1/tournaments/{tournament.id}/bet-markets",
        json={
            "bet_type": "champion",
            "label": "Campeón",
            "opens_at": "2020-01-01T00:00:00Z",
            "closes_at": "2099-01-01T00:00:00Z",
        },
        headers=admin_headers,
    )
    market_id = market.json()["id"]

    bet = await client.post(
        f"/api/v1/bet-markets/{market_id}/predictions",
        json={"payload": {"team_id": team.id}, "stake_amount": 10.0},
        headers=admin_headers,
    )
    # No access pass at all, yet admins bypass the gate entirely.
    assert bet.status_code == 201
