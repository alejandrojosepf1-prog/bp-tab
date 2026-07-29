from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas.auth import (
    LoginRequest,
    MyPredictionOut,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import BetMarket, Prediction, Speaker, Team, Tournament, User
from app.models.enums import UserRole
from app.services.odds_service import format_payload_label

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_db)) -> User:
    existing = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # The very first account becomes admin: /admin/users (the only way to grant roles) itself
    # requires an admin, so a fresh deployment (e.g. a brand-new Neon database) previously had
    # no way to ever produce one without hand-editing the database.
    any_user = (await session.execute(select(User.id).limit(1))).scalar_one_or_none()
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=UserRole.ADMIN if any_user is None else UserRole.USER,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )
    access_token = create_access_token(str(user.id))
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/me/predictions", response_model=list[MyPredictionOut])
async def my_predictions(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MyPredictionOut]:
    """Full bet history for the logged-in user across every tournament, newest first."""
    rows = (
        await session.execute(
            select(Prediction, BetMarket, Tournament)
            .join(BetMarket, Prediction.bet_market_id == BetMarket.id)
            .join(Tournament, BetMarket.tournament_id == Tournament.id)
            .where(Prediction.user_id == current_user.id)
            .order_by(Prediction.created_at.desc())
        )
    ).all()

    # Batched per distinct tournament (usually just one or two for this friends-scale app)
    # rather than per-prediction, so labeling a long bet history doesn't N+1 query team/speaker
    # names -- format_payload_label itself is pure string formatting, no DB access.
    tournament_ids = {tournament.id for _, _, tournament in rows}
    team_names_by_tournament: dict[int, dict[int, tuple[str, str | None]]] = {}
    speaker_names_by_tournament: dict[int, dict[int, str]] = {}
    for tid in tournament_ids:
        team_names_by_tournament[tid] = {
            t.id: (t.name, t.emoji)
            for t in (
                await session.execute(select(Team).where(Team.tournament_id == tid))
            ).scalars()
        }
        speaker_names_by_tournament[tid] = {
            s.id: s.name
            for s in (
                await session.execute(select(Speaker).where(Speaker.tournament_id == tid))
            ).scalars()
        }

    out = []
    for prediction, market, tournament in rows:
        label, _emoji = format_payload_label(
            market.bet_type,
            prediction.payload,
            team_names=team_names_by_tournament[tournament.id],
            speaker_names=speaker_names_by_tournament[tournament.id],
        )
        out.append(
            MyPredictionOut(
                id=prediction.id,
                bet_market_id=market.id,
                market_label=market.label,
                bet_type=market.bet_type.value,
                market_status=market.status.value,
                tournament_id=tournament.id,
                tournament_name=tournament.name,
                selection_label=label,
                status=prediction.status.value,
                stake_amount=prediction.stake_amount,
                odds=prediction.odds,
                potential_payout=round(prediction.stake_amount * prediction.odds, 2),
                points_awarded=prediction.points_awarded,
                sub_bet_odds=prediction.sub_bet_odds,
                sub_bet_status=(
                    prediction.sub_bet_status.value if prediction.sub_bet_status else None
                ),
                sub_bet_points_awarded=prediction.sub_bet_points_awarded,
                created_at=prediction.created_at,
            )
        )
    return out
