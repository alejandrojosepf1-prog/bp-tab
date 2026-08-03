"""FastAPI dependencies for authentication/authorization.

`get_current_user` is the "hard" auth dependency (401 if missing/invalid/inactive) used by every
endpoint that requires a logged-in user. `get_current_user_optional` is the "soft" variant used
only by the dashboard, whose contract says `my_predictions` is included "only if authenticated"
rather than requiring auth outright. `require_admin` layers a role check on top of the hard
dependency for the endpoints the contract marks **(admin)**.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import JWTError, decode_access_token
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
_oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(_oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise _CREDENTIALS_EXCEPTION from exc

    # A plain login session token never carries a "purpose" claim -- special-purpose tokens
    # (e.g. access_pass_service's activation link) do, specifically so a real, unexpired,
    # correctly-signed activation token can never double as a login bypass just because its
    # `sub` happens to collide with a real user id.
    if payload.get("purpose") is not None:
        raise _CREDENTIALS_EXCEPTION

    raw_user_id = payload.get("sub")
    if raw_user_id is None:
        raise _CREDENTIALS_EXCEPTION
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError) as exc:
        raise _CREDENTIALS_EXCEPTION from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXCEPTION
    return user


async def get_current_user_optional(
    token: str | None = Depends(_oauth2_scheme_optional),
    session: AsyncSession = Depends(get_db),
) -> User | None:
    if token is None:
        return None
    try:
        return await get_current_user(token=token, session=session)
    except HTTPException:
        return None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )
    return user
