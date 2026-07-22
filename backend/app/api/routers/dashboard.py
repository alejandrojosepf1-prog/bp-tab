from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user_optional
from app.api.routers.betting import to_bet_market_out
from app.api.schemas.betting import PredictionOut
from app.api.schemas.dashboard import ChangeEventOut, DashboardOut
from app.api.schemas.leaderboard import LeaderboardEntryOut, LeaderboardUserOut
from app.api.schemas.rounds import RoundOut
from app.db.session import get_db
from app.models import BetMarket, ChangeEvent, LeaderboardEntry, Prediction, Round, User
from app.models.enums import BetMarketStatus
from app.services.tournament_service import get_current_round

router = APIRouter(prefix="/tournaments/{tournament_id}", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
async def get_dashboard(
    tournament_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> DashboardOut:
    # The round the tournament is actually at (see get_current_round) -- NOT simply the
    # highest-seq round, which used to surface a not-yet-drawn final as "latest" while the
    # round everyone was debating stayed invisible.
    current_round = await get_current_round(session, tournament_id)

    rounds = (
        (
            await session.execute(
                select(Round).where(Round.tournament_id == tournament_id).order_by(Round.seq)
            )
        )
        .scalars()
        .all()
    )

    recent_changes = (
        (
            await session.execute(
                select(ChangeEvent)
                .where(ChangeEvent.tournament_id == tournament_id)
                .order_by(ChangeEvent.detected_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    leaderboard_top = (
        (
            await session.execute(
                select(LeaderboardEntry)
                .where(LeaderboardEntry.tournament_id == tournament_id)
                .options(selectinload(LeaderboardEntry.user))
                .order_by(LeaderboardEntry.rank)
                .limit(5)
            )
        )
        .scalars()
        .all()
    )

    open_bet_markets = (
        (
            await session.execute(
                select(BetMarket).where(
                    BetMarket.tournament_id == tournament_id,
                    BetMarket.status == BetMarketStatus.OPEN,
                )
            )
        )
        .scalars()
        .all()
    )

    my_predictions: list[PredictionOut] | None = None
    if current_user is not None:
        predictions = (
            (
                await session.execute(
                    select(Prediction)
                    .join(BetMarket, Prediction.bet_market_id == BetMarket.id)
                    .where(
                        BetMarket.tournament_id == tournament_id,
                        Prediction.user_id == current_user.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        my_predictions = [PredictionOut.model_validate(p) for p in predictions]

    current_round_out = RoundOut.model_validate(current_round) if current_round else None
    return DashboardOut(
        current_round=current_round_out,
        latest_round=current_round_out,
        rounds=[RoundOut.model_validate(r) for r in rounds],
        recent_changes=[ChangeEventOut.model_validate(c) for c in recent_changes],
        leaderboard_top=[
            LeaderboardEntryOut(
                user=LeaderboardUserOut(id=e.user.id, display_name=e.user.display_name),
                total_points=e.total_points,
                rank=e.rank,
                computed_at=e.computed_at,
            )
            for e in leaderboard_top
        ],
        my_predictions=my_predictions,
        open_bet_markets=[await to_bet_market_out(session, m) for m in open_bet_markets],
    )
