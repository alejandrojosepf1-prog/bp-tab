"""Access requests + approval for one tournament (CNADE 2026 Roadmap Pieza 4).

Flow: a public form submits a request (`submit_access_pass_request`) -> an admin approves or
rejects it (`approve_access_pass` / `reject_access_pass`) -> approving finds-or-creates the
persistent `User` account and emails a signed activation link. None of this decides whether the
user can actually BET in the tournament -- that's `is_participant_of_tournament`, checked live
by `betting_service.place_prediction` against CURRENT scraped data, never cached here, per the
roadmap's explicit design ("el tab de CNADE puede aparecer tarde -- alguien aprobado hoy queda
correctamente bloqueado más adelante si el tab lo muestra como orador").
"""

import datetime
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import JWTError, create_access_token, decode_access_token, hash_password
from app.models import AccessPass, Adjudicator, Speaker, Tournament, User
from app.models.enums import AccessPassStatus, UserRole
from app.repositories.upsert import upsert_by_natural_key
from app.services.circuit_identity_service import normalize_name
from app.services.email_service import send_activation_email

# Distinguishes an activation link from a normal login session token -- see
# app.core.security.create_access_token's extra_claims and app.api.deps.get_current_user's
# rejection of any token carrying a "purpose" claim.
ACTIVATION_TOKEN_PURPOSE = "activate_access_pass"
ACTIVATION_TOKEN_EXPIRES = datetime.timedelta(days=7)


class AccessPassError(Exception):
    """Raised for any invalid access-pass operation -- the router maps this to a 400."""


async def _match_participant(
    session: AsyncSession, tournament_id: int, full_name: str
) -> dict | None:
    """Exact normalized match only against this tournament's Speakers/Adjudicators -- same
    conservative rule as circuit_identity_service.match_or_create_person, for the same reason
    (names collide constantly across the circuit; a fuzzy match here would wrongly block, or
    wrongly clear, the wrong person)."""
    key = normalize_name(full_name)
    speakers = (
        await session.execute(select(Speaker).where(Speaker.tournament_id == tournament_id))
    ).scalars().all()
    for speaker in speakers:
        if normalize_name(speaker.name) == key:
            return {"kind": "speaker", "id": speaker.id, "name": speaker.name}
    adjudicators = (
        await session.execute(select(Adjudicator).where(Adjudicator.tournament_id == tournament_id))
    ).scalars().all()
    for adjudicator in adjudicators:
        if normalize_name(adjudicator.name) == key:
            return {"kind": "adjudicator", "id": adjudicator.id, "name": adjudicator.name}
    return None


async def submit_access_pass_request(
    session: AsyncSession,
    tournament_id: int,
    *,
    email: str,
    phone: str,
    full_name: str,
) -> AccessPass:
    """Upserts by (tournament_id, email) -- resubmitting edits the same request rather than
    piling up duplicates. Resubmitting an already-APPROVED pass just refreshes the contact
    info/match hint; it does NOT reopen a review that's already done (an admin would have to
    revoke it deliberately, which this platform doesn't support yet -- see Active Priorities if
    that turns out to be needed)."""
    match_hint = await _match_participant(session, tournament_id, full_name)

    existing = (
        await session.execute(
            select(AccessPass).where(
                AccessPass.tournament_id == tournament_id, AccessPass.email == email
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == AccessPassStatus.APPROVED:
        existing.phone = phone
        existing.full_name = full_name
        existing.match_hint = match_hint
        await session.flush()
        return existing

    result = await upsert_by_natural_key(
        session,
        AccessPass,
        lookup={"tournament_id": tournament_id, "email": email},
        values={
            "phone": phone,
            "full_name": full_name,
            "status": AccessPassStatus.PENDING,
            "match_hint": match_hint,
        },
    )
    return result.instance


async def approve_access_pass(
    session: AsyncSession, access_pass: AccessPass, admin: User
) -> AccessPass:
    """Finds or creates the persistent `User` for `access_pass.email` (a returning user's
    account -- and password -- is reused untouched, per "cuenta persistente pero cada torneo
    exige aprobación de nuevo"; only a brand new account gets an unusable random password until
    the activation link sets a real one) and grants tournament access by flipping this pass to
    APPROVED. Then emails the activation link -- see module docstring for why that's a separate
    step from the grant itself."""
    if access_pass.status != AccessPassStatus.PENDING:
        raise AccessPassError("este pase ya fue revisado")

    tournament = await session.get(Tournament, access_pass.tournament_id)
    if tournament is None:
        raise AccessPassError("torneo no encontrado")

    user = (
        await session.execute(select(User).where(User.email == access_pass.email))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            email=access_pass.email,
            # Unusable until /auth/activate sets a real one -- nobody can log in with a
            # 32-byte random string as their "password".
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=access_pass.full_name,
            role=UserRole.USER,
        )
        session.add(user)
        await session.flush()

    access_pass.user_id = user.id
    access_pass.status = AccessPassStatus.APPROVED
    access_pass.reviewed_by_id = admin.id
    access_pass.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    await session.flush()

    token = create_access_token(
        str(access_pass.id),
        expires_delta=ACTIVATION_TOKEN_EXPIRES,
        extra_claims={"purpose": ACTIVATION_TOKEN_PURPOSE},
    )
    settings = get_settings()
    activation_url = f"{settings.frontend_base_url}/activate?token={token}"
    await send_activation_email(
        to_email=access_pass.email,
        full_name=access_pass.full_name,
        tournament_name=tournament.name,
        activation_url=activation_url,
    )
    return access_pass


async def reject_access_pass(
    session: AsyncSession, access_pass: AccessPass, admin: User
) -> AccessPass:
    if access_pass.status != AccessPassStatus.PENDING:
        raise AccessPassError("este pase ya fue revisado")
    access_pass.status = AccessPassStatus.REJECTED
    access_pass.reviewed_by_id = admin.id
    access_pass.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    await session.flush()
    return access_pass


async def activate_access_pass(session: AsyncSession, token: str, *, password: str) -> User:
    """Redeems an activation link and sets `password` unconditionally -- always required,
    whether the account is brand new (its password_hash is the random unusable string
    `approve_access_pass` set, so it MUST be replaced before anyone can log in) or returning
    (setting it again is just a harmless reset, and there's no reliable signal here to tell the
    two cases apart without extra state, so treating them the same is both simpler and safer)."""
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise AccessPassError("el enlace es inválido o venció") from exc
    if payload.get("purpose") != ACTIVATION_TOKEN_PURPOSE:
        raise AccessPassError("el enlace es inválido")
    if len(password) < 8:
        raise AccessPassError("la contraseña debe tener al menos 8 caracteres")

    raw_pass_id = payload.get("sub")
    try:
        access_pass = await session.get(AccessPass, int(raw_pass_id))
    except (TypeError, ValueError):
        access_pass = None
    if (
        access_pass is None
        or access_pass.status != AccessPassStatus.APPROVED
        or access_pass.user_id is None
    ):
        raise AccessPassError("el enlace es inválido")

    user = await session.get(User, access_pass.user_id)
    if user is None:
        raise AccessPassError("la cuenta ya no existe")

    user.password_hash = hash_password(password)
    return user


async def has_approved_access(session: AsyncSession, tournament_id: int, user: User) -> bool:
    stmt = select(AccessPass.id).where(
        AccessPass.tournament_id == tournament_id,
        AccessPass.user_id == user.id,
        AccessPass.status == AccessPassStatus.APPROVED,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def is_participant_of_tournament(
    session: AsyncSession, tournament_id: int, user: User
) -> bool:
    """Live re-check against CURRENT scraped data, never cached -- a tab published mid-tournament
    can turn someone who wasn't a participant at approval time into one. Only meaningful for a
    user with an APPROVED pass for this tournament (that's where their on-file `full_name`
    comes from); a user with none has nothing here to check against."""
    access_pass = (
        await session.execute(
            select(AccessPass).where(
                AccessPass.tournament_id == tournament_id,
                AccessPass.user_id == user.id,
                AccessPass.status == AccessPassStatus.APPROVED,
            )
        )
    ).scalar_one_or_none()
    if access_pass is None:
        return False
    return await _match_participant(session, tournament_id, access_pass.full_name) is not None
