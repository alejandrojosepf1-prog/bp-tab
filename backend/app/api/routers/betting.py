import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.api.schemas.betting import (
    BetMarketCreate,
    BetMarketOut,
    BetMarketPatch,
    PredictionCreate,
    PredictionOut,
    SettleRequest,
    SettleResponse,
)
from app.db.session import get_db
from app.models import BetMarket, Prediction, Tournament, User
from app.models.enums import BetMarketStatus, PredictionStatus
from app.repositories.upsert import upsert_by_natural_key
from app.services.betting_service import set_bet_market_status, settle_market

router = APIRouter(tags=["betting"])


async def _get_tournament_or_404(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await session.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


async def _get_market_or_404(session: AsyncSession, market_id: int) -> BetMarket:
    market = await session.get(BetMarket, market_id)
    if market is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bet market not found")
    return market


@router.get("/tournaments/{tournament_id}/bet-markets", response_model=list[BetMarketOut])
async def list_bet_markets(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[BetMarket]:
    stmt = (
        select(BetMarket)
        .where(BetMarket.tournament_id == tournament_id)
        .order_by(BetMarket.opens_at)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.post(
    "/tournaments/{tournament_id}/bet-markets",
    response_model=BetMarketOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_bet_market(
    tournament_id: int,
    payload: BetMarketCreate,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BetMarket:
    await _get_tournament_or_404(session, tournament_id)
    market = BetMarket(
        tournament_id=tournament_id,
        bet_type=payload.bet_type,
        label=payload.label,
        description=payload.description,
        opens_at=payload.opens_at,
        closes_at=payload.closes_at,
        points_rule=payload.points_rule or {},
        target_round_id=payload.target_round_id,
        target_break_category_id=payload.target_break_category_id,
    )
    session.add(market)
    await session.commit()
    await session.refresh(market)
    return market


@router.patch("/bet-markets/{market_id}", response_model=BetMarketOut)
async def patch_bet_market(
    market_id: int,
    payload: BetMarketPatch,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BetMarket:
    market = await _get_market_or_404(session, market_id)
    if payload.status is not None:
        try:
            set_bet_market_status(market, payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(market)
    return market


@router.post("/bet-markets/{market_id}/settle", response_model=SettleResponse)
async def settle_bet_market(
    market_id: int,
    payload: SettleRequest,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SettleResponse:
    market = await _get_market_or_404(session, market_id)
    settled = await settle_market(session, market, manual_outcome=payload.manual_outcome)
    await session.commit()
    return SettleResponse(settled=settled)


@router.get("/bet-markets/{market_id}/predictions/me", response_model=PredictionOut | None)
async def get_my_prediction(
    market_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Prediction | None:
    await _get_market_or_404(session, market_id)
    stmt = select(Prediction).where(
        Prediction.bet_market_id == market_id, Prediction.user_id == current_user.id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.post(
    "/bet-markets/{market_id}/predictions",
    response_model=PredictionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_prediction(
    market_id: int,
    payload: PredictionCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Prediction:
    market = await _get_market_or_404(session, market_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    closes_at = market.closes_at
    if closes_at.tzinfo is None:
        closes_at = closes_at.replace(tzinfo=datetime.timezone.utc)
    if market.status != BetMarketStatus.OPEN or now >= closes_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This bet market is not open for predictions",
        )

    result = await upsert_by_natural_key(
        session,
        Prediction,
        lookup={"bet_market_id": market_id, "user_id": current_user.id},
        values={
            "payload": payload.payload,
            "locked_at": now,
            "status": PredictionStatus.OPEN,
            "points_awarded": None,
        },
    )
    await session.commit()
    await session.refresh(result.instance)
    return result.instance
