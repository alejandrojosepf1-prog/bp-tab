from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas.admin import (
    AdminUserUpdate,
    GameEconomyOut,
    ManualEliminationResultIn,
    MarketPayoutSpreadOut,
    PendingEliminationDebateOut,
    PendingEliminationTeamOut,
    RoundMotionCategoryOut,
    RoundMotionCategoryPatch,
    ScrapeLogOut,
)
from app.api.schemas.auth import UserOut
from app.db.session import get_db
from app.models import BetMarket, Round, ScrapeLog, User
from app.models.enums import BetMarketStatus
from app.services.game_economy_service import compute_game_economy, compute_market_payout_spread
from app.services.manual_results_service import (
    ManualResultError,
    apply_manual_advancing_teams,
    apply_manual_champion,
    get_pending_elimination_debates,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/scrape-logs", response_model=list[ScrapeLogOut])
async def list_scrape_logs(
    tournament_id: int | None = None, session: AsyncSession = Depends(get_db)
) -> list[ScrapeLog]:
    stmt = select(ScrapeLog)
    if tournament_id is not None:
        stmt = stmt.where(ScrapeLog.tournament_id == tournament_id)
    stmt = stmt.order_by(ScrapeLog.started_at.desc())
    return list((await session.execute(stmt)).scalars().all())


@router.get("/users", response_model=list[UserOut])
async def list_users(session: AsyncSession = Depends(get_db)) -> list[User]:
    stmt = select(User).order_by(User.id)
    return list((await session.execute(stmt)).scalars().all())


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, payload: AdminUserUpdate, session: AsyncSession = Depends(get_db)
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/pending-elimination-results", response_model=list[PendingEliminationDebateOut])
async def list_pending_elimination_results(
    tournament_id: int | None = None, session: AsyncSession = Depends(get_db)
) -> list[PendingEliminationDebateOut]:
    """Elimination-round debates (including the Grand Final) whose draw is known but whose
    result Tabbycat hasn't published -- surfaced here so an admin can enter it by hand instead
    of editing the database directly. See app.services.manual_results_service."""
    pending = await get_pending_elimination_debates(session, tournament_id)
    return [
        PendingEliminationDebateOut(
            debate_id=item.debate.id,
            tournament_id=item.debate.tournament_id,
            round_id=item.round.id,
            round_name=item.round.name,
            is_final=item.is_final,
            teams=[
                PendingEliminationTeamOut(team_id=dt.team_id, team_name=dt.team.name)
                for dt in item.debate.teams
            ],
        )
        for item in pending
    ]


@router.get("/game-economy", response_model=GameEconomyOut)
async def get_game_economy(
    tournament_id: int | None = None, session: AsyncSession = Depends(get_db)
) -> GameEconomyOut:
    """Derived token-economy view (there is no house to fund or protect -- see
    app.services.game_economy_service's module docstring): tokens in circulation, volume,
    whether the economy is net inflating, and a per-market payout-spread projection over
    currently-OPEN predictions."""
    summary = await compute_game_economy(session, tournament_id)

    stmt = select(BetMarket).where(BetMarket.status == BetMarketStatus.OPEN)
    if tournament_id is not None:
        stmt = stmt.where(BetMarket.tournament_id == tournament_id)
    open_markets = (await session.execute(stmt)).scalars().all()

    spreads = []
    for market in open_markets:
        spread = await compute_market_payout_spread(session, market)
        if spread is not None:
            spreads.append(spread)

    return GameEconomyOut(
        total_staked_open=summary.total_staked_open,
        total_staked_settled=summary.total_staked_settled,
        total_paid_out=summary.total_paid_out,
        net_token_inflation=summary.net_token_inflation,
        tokens_in_circulation=summary.tokens_in_circulation,
        open_predictions_count=summary.open_predictions_count,
        settled_predictions_count=summary.settled_predictions_count,
        active_bettors_count=summary.active_bettors_count,
        payout_spread=[
            MarketPayoutSpreadOut(
                market_id=s.market_id,
                market_label=s.market_label,
                pool_total=s.pool_total,
                worst_case=s.worst_case,
                best_case=s.best_case,
            )
            for s in spreads
        ],
        payout_spread_worst_case_total=sum(s.worst_case for s in spreads),
        payout_spread_best_case_total=sum(s.best_case for s in spreads),
    )


@router.patch("/rounds/{round_id}/motion-category", response_model=RoundMotionCategoryOut)
async def set_round_motion_category(
    round_id: int, payload: RoundMotionCategoryPatch, session: AsyncSession = Depends(get_db)
) -> RoundMotionCategoryOut:
    """Loads (or clears) the round's motion-category ground truth for the MOTION_TYPE market --
    meant to be filled in BEFORE the motion is revealed to debaters, from the same info the
    Equipo de Adjudicación already has. Never returned by any public endpoint; see
    RoundMotionCategoryOut's docstring."""
    round_ = await session.get(Round, round_id)
    if round_ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Round not found")
    round_.motion_category = payload.motion_category
    await session.commit()
    return RoundMotionCategoryOut(round_id=round_.id, motion_category=round_.motion_category)


@router.post("/debates/{debate_id}/manual-result")
async def submit_manual_elimination_result(
    debate_id: int, payload: ManualEliminationResultIn, session: AsyncSession = Depends(get_db)
) -> dict:
    try:
        if payload.champion_team_id is not None:
            await apply_manual_champion(session, debate_id, payload.champion_team_id)
        else:
            assert payload.advancing_team_ids is not None
            await apply_manual_advancing_teams(session, debate_id, payload.advancing_team_ids)
    except ManualResultError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return {"status": "ok"}
