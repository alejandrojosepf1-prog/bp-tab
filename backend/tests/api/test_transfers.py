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


async def test_transfer_cap_allows_up_to_max_received_across_multiple_senders(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The cap is cumulative RECEIVED, summed across every sender -- not a per-transfer limit a
    determined pair could route around with several smaller transfers."""
    tournament = await make_tournament(db_session)
    alice = await make_user(
        db_session, email="alice-cap1@example.com", tournament=tournament, balance=100.0
    )
    carol = await make_user(
        db_session, email="carol-cap1@example.com", tournament=tournament, balance=100.0
    )
    dave = await make_user(db_session, email="dave-cap1@example.com")

    first = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": dave.id, "amount": 60.0, "tournament_id": tournament.id},
        headers=auth_headers(alice),
    )
    assert first.status_code == 201

    # 60 + 40 = exactly the 100-token cap -- right at the boundary, must still succeed.
    second = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": dave.id, "amount": 40.0, "tournament_id": tournament.id},
        headers=auth_headers(carol),
    )
    assert second.status_code == 201

    dave_balance = await client.get(
        f"/api/v1/tournaments/{tournament.id}/me/balance", headers=auth_headers(dave)
    )
    assert dave_balance.json()["balance"] == 200.0  # 100 start + 60 + 40


async def test_transfer_rejects_once_recipient_would_exceed_received_cap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await make_tournament(db_session)
    alice = await make_user(
        db_session, email="alice-cap2@example.com", tournament=tournament, balance=100.0
    )
    bob = await make_user(
        db_session, email="bob-cap2@example.com", tournament=tournament, balance=100.0
    )
    dave = await make_user(db_session, email="dave-cap2@example.com")
    # Headers/IDs captured up front, before the rejected transfer's rollback expires the
    # session's ORM objects (same MissingGreenlet trap as test_betting.py's motion_type test
    # and the sibling insufficient-balance test above).
    tournament_id = tournament.id
    dave_id = dave.id
    alice_headers, bob_headers, dave_headers = (
        auth_headers(alice), auth_headers(bob), auth_headers(dave)
    )

    first = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": dave_id, "amount": 60.0, "tournament_id": tournament_id},
        headers=alice_headers,
    )
    assert first.status_code == 201

    # 60 already received + 50 more = 110 > the 100-token cap -- rejected WHOLE, not trimmed to
    # the 40 that would still fit.
    second = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": dave_id, "amount": 50.0, "tournament_id": tournament_id},
        headers=bob_headers,
    )
    assert second.status_code == 400

    dave_balance = await client.get(
        f"/api/v1/tournaments/{tournament_id}/me/balance", headers=dave_headers
    )
    assert dave_balance.json()["balance"] == 160.0  # 100 start + 60 only -- the 50 never landed


async def test_transfer_received_cap_is_scoped_per_tournament(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    t1 = await make_tournament(db_session)
    t2 = await make_tournament(db_session)
    alice = await make_user(
        db_session, email="alice-cap3@example.com", tournament=t1, balance=100.0
    )
    bob = await make_user(db_session, email="bob-cap3@example.com", tournament=t2, balance=100.0)
    dave = await make_user(db_session, email="dave-cap3@example.com")

    maxed_out = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": dave.id, "amount": 100.0, "tournament_id": t1.id},
        headers=auth_headers(alice),
    )
    assert maxed_out.status_code == 201

    # Dave already received the full cap in t1 -- but t2 is a separate tournament with its own
    # TournamentBalance and its own cap, so this must succeed, not inherit t1's exhausted cap.
    in_other_tournament = await client.post(
        "/api/v1/transfers",
        json={"recipient_id": dave.id, "amount": 100.0, "tournament_id": t2.id},
        headers=auth_headers(bob),
    )
    assert in_other_tournament.status_code == 201


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