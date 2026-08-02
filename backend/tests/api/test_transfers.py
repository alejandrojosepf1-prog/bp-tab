from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.conftest import auth_headers, make_tournament, make_user


async def test_transfer_moves_balance_and_writes_both_ledger_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await make_tournament(db_session)
    alice = await make_user(
        db_session, email="alice-transfer@example.com", tournament=tournament, balance=100.0
    )
    bob = await make_user(
        db_session, email="bob-transfer@example.com", tournament=tournament, balance=50.0
    )
    alice_headers = auth_headers(alice)

    response = await client.post(
        "/api/v1/transfers",
        json={
            "recipient_id": bob.id,
            "amount": 30.0,
            "tournament_id": tournament.id,
            "note": "para la ronda que viene",
        },
        headers=alice_headers,
    )
    assert response.status_code == 201
    sent = response.json()["sent"]
    assert sent["type"] == "transfer_out"
    assert sent["amount"] == 30.0
    assert sent["balance_after"] == 70.0
    assert sent["counterparty_display_name"] == bob.display_name

    me = await client.get(f"/api/v1/tournaments/{tournament.id}/me/balance", headers=alice_headers)
    assert me.json()["balance"] == 70.0

    bob_headers = auth_headers(bob)
    bob_me = await client.get(
        f"/api/v1/tournaments/{tournament.id}/me/balance", headers=bob_headers
    )
    assert bob_me.json()["balance"] == 80.0

    bob_history = await client.get("/api/v1/transfers/me", headers=bob_headers)
    assert bob_history.status_code == 200
    received = bob_history.json()[0]
    assert received["type"] == "transfer_in"
    assert received["amount"] == 30.0
    assert received["balance_after"] == 80.0
    assert received["counterparty_display_name"] == alice.display_name


async def test_transfer_rejects_insufficient_balance_self_and_below_minimum(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await make_tournament(db_session)
    alice = await make_user(
        db_session, email="alice-transfer2@example.com", tournament=tournament, balance=10.0
    )
    bob = await make_user(db_session, email="bob-transfer2@example.com")
    headers = auth_headers(alice)
    # IDs captured up front: a 400 rolls back the app's own session, expiring these ORM objects
    # (see the identical fix in test_betting.py's motion_type test for the full explanation).
    # tournament.id included here too -- it's re-evaluated in every request's json body below,
    # so it's just as vulnerable to the same post-rollback MissingGreenlet as alice_id/bob_id.
    alice_id, bob_id, tournament_id = alice.id, bob.id, tournament.id

    too_much = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": bob_id, "amount": 500.0, "tournament_id": tournament_id},
        headers=headers,
    )
    assert too_much.status_code == 400

    to_self = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": alice_id, "amount": 5.0, "tournament_id": tournament_id},
        headers=headers,
    )
    assert to_self.status_code == 400

    too_small = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": bob_id, "amount": 0.5, "tournament_id": tournament_id},
        headers=headers,
    )
    assert too_small.status_code == 400

    unchanged = await client.get(
        f"/api/v1/tournaments/{tournament_id}/me/balance", headers=headers
    )
    assert unchanged.json()["balance"] == 10.0


async def test_list_users_excludes_self_and_inactive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    alice = await make_user(db_session, email="alice-users@example.com", display_name="Alice")
    bob = await make_user(db_session, email="bob-users@example.com", display_name="Bob")
    await make_user(
        db_session, email="inactive-users@example.com", display_name="Ghost", is_active=False
    )

    response = await client.get("/api/v1/auth/users", headers=auth_headers(alice))
    assert response.status_code == 200
    ids = {u["id"] for u in response.json()}
    assert alice.id not in ids
    assert bob.id in ids
    assert "Ghost" not in {u["display_name"] for u in response.json()}