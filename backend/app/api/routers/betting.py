import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.api.schemas.betting import (
    BetMarketCreate,
    BetMarketOut,
    BetMarketPatch,
    MarketBoardOptionOut,
    MarketBoardOut,
    OddsQuoteOut,
    OddsQuoteRequest,
    PredictionCreate,
    PredictionOut,
    SettleRequest,
    SettleResponse,
)
from app.db.session import get_db
from app.models import BetMarket, Prediction, Tournament, User
from app.models.enums import BetMarketStatus
from app.services.betting_service import (
    InsufficientBalanceError,
    MarketCreationError,
    place_prediction,
    set_bet_market_status,
    settle_market,
    validate_market_creation,
)
from app.services.odds_service import UnpriceableMarketError, market_board, quote_odds

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


async def _pool_total(session: AsyncSession, market_id: int) -> float:
    total = (
        await session.execute(
            select(func.coalesce(func.sum(Prediction.stake_amount), 0.0)).where(
                Prediction.bet_market_id == market_id
            )
        )
    ).scalar_one()
    return float(total)


async def to_bet_market_out(session: AsyncSession, market: BetMarket) -> BetMarketOut:
    """Shared by this router AND the dashboard: pool_total/bettors_count are computed, not
    columns, so any endpoint returning a BetMarketOut must fill them the same way -- the
    dashboard used to skip this and permanently showed pool $0 for markets that had real
    stakes on the betting page."""
    out = BetMarketOut.model_validate(market)
    out.pool_total = await _pool_total(session, market.id)
    out.bettors_count = int(
        (
            await session.execute(
                select(func.count(func.distinct(Prediction.user_id))).where(
                    Prediction.bet_market_id == market.id
                )
            )
        ).scalar_one()
    )
    return out


_to_bet_market_out = to_bet_market_out


def _to_prediction_out(prediction: Prediction) -> PredictionOut:
    out = PredictionOut.model_validate(prediction)
    out.potential_payout = round(prediction.stake_amount * prediction.odds, 2)
    return out


@router.get("/tournaments/{tournament_id}/bet-markets", response_model=list[BetMarketOut])
async def list_bet_markets(
    tournament_id: int, session: AsyncSession = Depends(get_db)
) -> list[BetMarketOut]:
    stmt = (
        select(BetMarket)
        .where(BetMarket.tournament_id == tournament_id)
        .order_by(BetMarket.opens_at)
    )
    markets = (await session.execute(stmt)).scalars().all()
    return [await _to_bet_market_out(session, m) for m in markets]


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
) -> BetMarketOut:
    tournament = await _get_tournament_or_404(session, tournament_id)
    try:
        validate_market_creation(
            tournament,
            payload.bet_type,
            target_round_id=payload.target_round_id,
            target_break_category_id=payload.target_break_category_id,
        )
    except MarketCreationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
    return await _to_bet_market_out(session, market)


@router.patch("/bet-markets/{market_id}", response_model=BetMarketOut)
async def patch_bet_market(
    market_id: int,
    payload: BetMarketPatch,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BetMarketOut:
    market = await _get_market_or_404(session, market_id)
    if payload.status is not None:
        try:
            set_bet_market_status(market, payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(market)
    return await _to_bet_market_out(session, market)


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


@router.get("/bet-markets/{market_id}/board", response_model=MarketBoardOut)
async def get_bet_market_board(
    market_id: int, session: AsyncSession = Depends(get_db)
) -> MarketBoardOut:
    """Live per-option view of a market: how much is staked on each candidate, by how many
    users, and the CURRENT quoted odds (seeded pari-mutuel) -- what the 'Mercados abiertos'
    section renders. Public: no auth, mirrors the market list itself."""
    market = await _get_market_or_404(session, market_id)
    board = await market_board(session, market)
    return MarketBoardOut(
        market=await _to_bet_market_out(session, market),
        pool_total=board.pool_total,
        bettors=board.bettors,
        options=[
            MarketBoardOptionOut(
                key=o.key,
                label=o.label,
                emoji=o.emoji,
                stake=o.stake,
                backers=o.backers,
                odds=o.odds,
            )
            for o in board.options
        ],
    )


@router.post("/bet-markets/{market_id}/quote", response_model=OddsQuoteOut)
async def quote_bet_market_odds(
    market_id: int,
    payload: OddsQuoteRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OddsQuoteOut:
    """Live odds preview for a candidate pick, WITHOUT placing a bet -- the frontend calls this
    as the user builds their pick so they can see "cuota: 1.85x" before committing a stake. Read
    -only: no Prediction is created, no balance touched."""
    market = await _get_market_or_404(session, market_id)
    try:
        odds = await quote_odds(session, market, payload.payload, exclude_user_id=current_user.id)
    except UnpriceableMarketError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid pick for this market: {exc}",
        ) from exc
    return OddsQuoteOut(odds=odds)


@router.get("/bet-markets/{market_id}/predictions/me", response_model=PredictionOut | None)
async def get_my_prediction(
    market_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PredictionOut | None:
    await _get_market_or_404(session, market_id)
    stmt = select(Prediction).where(
        Prediction.bet_market_id == market_id, Prediction.user_id == current_user.id
    )
    prediction = (await session.execute(stmt)).scalar_one_or_none()
    return _to_prediction_out(prediction) if prediction else None


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
) -> PredictionOut:
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
    if payload.stake_amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="stake_amount must be greater than 0",
        )

    try:
        prediction = await place_prediction(
            session, market, current_user, payload.payload, payload.stake_amount
        )
    except UnpriceableMarketError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid pick for this market: {exc}",
        ) from exc
    except InsufficientBalanceError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(prediction)
    return _to_prediction_out(prediction)
