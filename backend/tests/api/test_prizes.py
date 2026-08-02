import datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tournament
from app.models.enums import TournamentStatus, UserRole
from tests.api.conftest import auth_headers, make_user

NOW = datetime.datetime.now(datetime.timezone.utc)


async def _make_tournament(db_session: AsyncSession) -> Tournament:
    tournament = Tournament(
        name="Prize Cup", slug="prize-cup", source_base_url="https://example.calicotab.com",
        source_slug="open", status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.commit()
    await db_session.refresh(tournament)
    return tournament


async def test_only_admin_can_create_prize_event(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)
    user = await make_user(db_session, email="user@example.com")

    denied = await client.post(
        f"/api/v1/tournaments/{tournament.id}/prize-events",
        json={"type": "manual_award", "title": "Sorpresa"},
        headers=auth_headers(user),
    )
    assert denied.status_code == 403

    admin = await make_user(db_session, email="admin@example.com", role=UserRole.ADMIN)
    created = await client.post(
        f"/api/v1/tournaments/{tournament.id}/prize-events",
        json={"type": "manual_award", "title": "Sorpresa"},
        headers=auth_headers(admin),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "open"
    assert body["entry_count"] == 0


async def test_manual_award_full_flow_via_api(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)
    admin = await make_user(db_session, email="admin2@example.com", role=UserRole.ADMIN)
    winner = await make_user(
        db_session, email="winner@example.com", tournament=tournament, balance=0.0
    )

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/prize-events",
        json={"type": "manual_award", "title": "Trivia BP"},
        headers=auth_headers(admin),
    )
    event_id = create_response.json()["id"]

    queue_response = await client.post(
        f"/api/v1/prize-events/{event_id}/manual-awards",
        json={"user_id": winner.id, "amount": 40.0},
        headers=auth_headers(admin),
    )
    assert queue_response.status_code == 201

    resolve_response = await client.post(
        f"/api/v1/prize-events/{event_id}/resolve", headers=auth_headers(admin)
    )
    assert resolve_response.status_code == 200
    body = resolve_response.json()
    assert body["status"] == "resolved"
    assert body["entries"][0]["awarded_amount"] == 40.0

    me_response = await client.get(
        f"/api/v1/tournaments/{tournament.id}/me/balance", headers=auth_headers(winner)
    )
    assert me_response.json()["balance"] == 40.0

    # Resolving twice is refused, not silently a no-op that would double-pay.
    second_resolve = await client.post(
        f"/api/v1/prize-events/{event_id}/resolve", headers=auth_headers(admin)
    )
    assert second_resolve.status_code == 400


async def test_raffle_entry_requires_auth_and_respects_balance(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)
    admin = await make_user(db_session, email="admin3@example.com", role=UserRole.ADMIN)
    entrant = await make_user(
        db_session, email="entrant@example.com", tournament=tournament, balance=10.0
    )

    create_response = await client.post(
        f"/api/v1/tournaments/{tournament.id}/prize-events",
        json={
            "type": "raffle",
            "title": "Sorteo de la final",
            "config": {"num_winners": 1, "prize_per_winner": 20.0, "ticket_cost": 5.0},
        },
        headers=auth_headers(admin),
    )
    event_id = create_response.json()["id"]

    unauthenticated = await client.post(
        f"/api/v1/prize-events/{event_id}/enter", json={"tickets": 1}
    )
    assert unauthenticated.status_code == 401

    entered = await client.post(
        f"/api/v1/prize-events/{event_id}/enter",
        json={"tickets": 2},
        headers=auth_headers(entrant),
    )
    assert entered.status_code == 201
    assert entered.json()["tickets"] == 2

    too_many = await client.post(
        f"/api/v1/prize-events/{event_id}/enter",
        json={"tickets": 100},
        headers=auth_headers(entrant),
    )
    assert too_many.status_code == 400

    resolved = await client.post(
        f"/api/v1/prize-events/{event_id}/resolve", headers=auth_headers(admin)
    )
    assert resolved.status_code == 200
    entries = resolved.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["awarded_amount"] == 20.0  # only entrant -- guaranteed winner


async def test_list_and_detail_prize_events_are_public(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tournament = await _make_tournament(db_session)
    admin = await make_user(db_session, email="admin4@example.com", role=UserRole.ADMIN)
    await client.post(
        f"/api/v1/tournaments/{tournament.id}/prize-events",
        json={"type": "manual_award", "title": "Público"},
        headers=auth_headers(admin),
    )

    listing = await client.get(f"/api/v1/tournaments/{tournament.id}/prize-events")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = await client.get(f"/api/v1/prize-events/{listing.json()[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["entries"] == []


async def test_get_unknown_prize_event_404s(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.get("/api/v1/prize-events/999999")
    assert response.status_code == 404
