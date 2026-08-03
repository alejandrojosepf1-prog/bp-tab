import pytest

from app.core.security import create_access_token, decode_access_token, verify_password
from app.models import AccessPass, Adjudicator, Speaker, Tournament, User
from app.models.enums import AccessPassStatus, TournamentStatus, UserRole
from app.services.access_pass_service import (
    ACTIVATION_TOKEN_PURPOSE,
    AccessPassError,
    activate_access_pass,
    approve_access_pass,
    has_approved_access,
    is_participant_of_tournament,
    reject_access_pass,
    submit_access_pass_request,
)

_seq = 0


async def _make_tournament(db_session) -> Tournament:
    global _seq
    _seq += 1
    tournament = Tournament(
        name=f"T{_seq}",
        slug=f"t{_seq}",
        source_base_url="https://x",
        source_slug=f"o{_seq}",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _make_user(db_session, email: str, *, role: UserRole = UserRole.USER) -> User:
    user = User(email=email, password_hash="x", display_name=email, role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_admin(db_session, email: str = "admin@example.com") -> User:
    return await _make_user(db_session, email, role=UserRole.ADMIN)


# --- matching -------------------------------------------------------------------------------


async def test_submit_request_matches_an_existing_speaker(db_session) -> None:
    tournament = await _make_tournament(db_session)
    speaker = Speaker(tournament_id=tournament.id, name="Fernanda Crousillat")
    db_session.add(speaker)
    await db_session.flush()

    access_pass = await submit_access_pass_request(
        db_session,
        tournament.id,
        email="fernanda@example.com",
        phone="+51 999",
        # Casing/accents differ from the scraped name -- normalize_name must still match.
        full_name="fernanda CROUSILLAT",
    )
    assert access_pass.match_hint == {
        "kind": "speaker",
        "id": speaker.id,
        "name": "Fernanda Crousillat",
    }


async def test_submit_request_matches_an_existing_adjudicator(db_session) -> None:
    tournament = await _make_tournament(db_session)
    adjudicator = Adjudicator(tournament_id=tournament.id, external_id=1, name="Juan Pérez")
    db_session.add(adjudicator)
    await db_session.flush()

    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="juan@example.com", phone="+51 999", full_name="Juan Perez"
    )
    assert access_pass.match_hint == {"kind": "adjudicator", "id": adjudicator.id, "name": "Juan Pérez"}


async def test_submit_request_no_match_leaves_hint_none(db_session) -> None:
    tournament = await _make_tournament(db_session)
    access_pass = await submit_access_pass_request(
        db_session,
        tournament.id,
        email="nadie@example.com",
        phone="+51 999",
        full_name="Nadie Conocido",
    )
    assert access_pass.match_hint is None


async def test_resubmit_updates_the_same_pending_row_not_a_duplicate(db_session) -> None:
    tournament = await _make_tournament(db_session)
    first = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="1", full_name="A One"
    )
    await db_session.commit()

    second = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="2", full_name="A Two"
    )
    await db_session.commit()

    assert first.id == second.id
    assert second.phone == "2"
    assert second.full_name == "A Two"
    assert second.status == AccessPassStatus.PENDING


async def test_resubmit_after_approval_does_not_reopen_review(db_session) -> None:
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="1", full_name="A One"
    )
    await db_session.commit()
    await approve_access_pass(db_session, access_pass, admin)
    await db_session.commit()

    resubmitted = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="9", full_name="A One"
    )
    assert resubmitted.id == access_pass.id
    assert resubmitted.status == AccessPassStatus.APPROVED  # untouched, not reset to pending
    assert resubmitted.phone == "9"  # contact info still refreshed


# --- approve / reject -------------------------------------------------------------------------


async def test_approve_creates_a_new_user_and_grants_access(db_session) -> None:
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="new@example.com", phone="1", full_name="New Person"
    )
    await db_session.commit()

    approved = await approve_access_pass(db_session, access_pass, admin)
    await db_session.commit()

    assert approved.status == AccessPassStatus.APPROVED
    assert approved.reviewed_by_id == admin.id
    assert approved.reviewed_at is not None
    assert approved.user_id is not None
    user = await db_session.get(User, approved.user_id)
    assert user.email == "new@example.com"
    assert await has_approved_access(db_session, tournament.id, user)


async def test_approve_reuses_an_existing_users_account(db_session) -> None:
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    returning = await _make_user(db_session, "returning@example.com")
    original_hash = returning.password_hash
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="returning@example.com", phone="1", full_name="Returning"
    )
    await db_session.commit()

    approved = await approve_access_pass(db_session, access_pass, admin)
    await db_session.commit()

    assert approved.user_id == returning.id
    assert returning.password_hash == original_hash  # never touched


async def test_approve_twice_raises(db_session) -> None:
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="1", full_name="A"
    )
    await db_session.commit()
    await approve_access_pass(db_session, access_pass, admin)
    await db_session.commit()

    with pytest.raises(AccessPassError):
        await approve_access_pass(db_session, access_pass, admin)


async def test_reject_then_resubmit_goes_back_to_pending(db_session) -> None:
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="1", full_name="A"
    )
    await db_session.commit()
    rejected = await reject_access_pass(db_session, access_pass, admin)
    await db_session.commit()
    assert rejected.status == AccessPassStatus.REJECTED

    with pytest.raises(AccessPassError):
        await reject_access_pass(db_session, access_pass, admin)  # already reviewed

    resubmitted = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="1", full_name="A"
    )
    assert resubmitted.status == AccessPassStatus.PENDING


# --- activation --------------------------------------------------------------------------------


async def test_activate_sets_password_and_returns_the_user(db_session) -> None:
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="new@example.com", phone="1", full_name="New Person"
    )
    await db_session.commit()
    approved = await approve_access_pass(db_session, access_pass, admin)
    await db_session.commit()

    token = create_access_token(
        str(approved.id), extra_claims={"purpose": ACTIVATION_TOKEN_PURPOSE}
    )
    user = await activate_access_pass(db_session, token, password="a-real-password")
    assert user.id == approved.user_id
    assert verify_password("a-real-password", user.password_hash)


async def test_activate_rejects_a_token_missing_the_activation_purpose(db_session) -> None:
    # A plain login token for some real user id -- must never work as an activation link.
    token = create_access_token("1")
    with pytest.raises(AccessPassError):
        await activate_access_pass(db_session, token, password="a-real-password")


async def test_activate_rejects_a_pending_or_rejected_pass(db_session) -> None:
    tournament = await _make_tournament(db_session)
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="1", full_name="A"
    )
    await db_session.commit()
    token = create_access_token(
        str(access_pass.id), extra_claims={"purpose": ACTIVATION_TOKEN_PURPOSE}
    )
    with pytest.raises(AccessPassError):
        await activate_access_pass(db_session, token, password="a-real-password")


async def test_activate_rejects_a_short_password(db_session) -> None:
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="1", full_name="A"
    )
    await db_session.commit()
    approved = await approve_access_pass(db_session, access_pass, admin)
    await db_session.commit()
    token = create_access_token(
        str(approved.id), extra_claims={"purpose": ACTIVATION_TOKEN_PURPOSE}
    )
    with pytest.raises(AccessPassError):
        await activate_access_pass(db_session, token, password="short")


# --- live participant check ---------------------------------------------------------------------


async def test_is_participant_true_when_approved_pass_matches_current_data(db_session) -> None:
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    db_session.add(Speaker(tournament_id=tournament.id, name="Fernanda Crousillat"))
    await db_session.flush()
    access_pass = await submit_access_pass_request(
        db_session,
        tournament.id,
        email="fernanda@example.com",
        phone="1",
        full_name="Fernanda Crousillat",
    )
    await db_session.commit()
    approved = await approve_access_pass(db_session, access_pass, admin)
    await db_session.commit()
    user = await db_session.get(User, approved.user_id)

    assert await is_participant_of_tournament(db_session, tournament.id, user) is True


async def test_is_participant_false_without_an_approved_pass(db_session) -> None:
    tournament = await _make_tournament(db_session)
    user = await _make_user(db_session, "u@example.com")
    await db_session.commit()
    assert await is_participant_of_tournament(db_session, tournament.id, user) is False


async def test_is_participant_checks_live_data_not_the_stored_hint(db_session) -> None:
    """The match_hint computed at submission time is informational only -- a participant
    scraped in AFTER approval must still get caught, because this re-checks fresh every time."""
    tournament = await _make_tournament(db_session)
    admin = await _make_admin(db_session)
    access_pass = await submit_access_pass_request(
        db_session, tournament.id, email="a@example.com", phone="1", full_name="Fernanda Crousillat"
    )
    await db_session.commit()
    assert access_pass.match_hint is None  # no speaker scraped yet at submission time
    approved = await approve_access_pass(db_session, access_pass, admin)
    await db_session.commit()
    user = await db_session.get(User, approved.user_id)
    assert await is_participant_of_tournament(db_session, tournament.id, user) is False

    # Tab publishes her as a speaker AFTER approval.
    db_session.add(Speaker(tournament_id=tournament.id, name="Fernanda Crousillat"))
    await db_session.commit()
    assert await is_participant_of_tournament(db_session, tournament.id, user) is True
