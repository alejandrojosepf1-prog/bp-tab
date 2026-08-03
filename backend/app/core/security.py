"""Password hashing and JWT create/decode helpers.

Kept dependency-light and framework-agnostic (no FastAPI imports here) so it can be unit
tested in isolation -- `app/api/deps.py` is the only place that wires this into a request.
"""

import datetime
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def create_access_token(
    subject: str,
    *,
    expires_delta: datetime.timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """`extra_claims` lets a caller stamp a token for a purpose other than "logged-in session"
    -- e.g. access_pass_service's activation link sets `{"purpose": "activate_access_pass"}` so
    `/auth/activate` can reject a token that's real and unexpired but was never meant for this,
    same idea as get_current_user rejecting a malformed/expired one."""
    settings = get_settings()
    expire = datetime.datetime.now(datetime.timezone.utc) + (
        expires_delta or datetime.timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode: dict[str, Any] = {"sub": subject, "exp": expire, **(extra_claims or {})}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises `jose.JWTError` on an invalid/expired token -- callers (app/api/deps.py)
    translate that into a 401."""
    settings = get_settings()
    decoded: dict[str, Any] = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    return decoded


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "JWTError",
]
