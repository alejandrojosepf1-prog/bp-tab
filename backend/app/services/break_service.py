"""Recomputes the Break Predictor for a break category and persists one snapshot per round.

Kept separate from `ranking_service` (which just answers "what are the standings") and from
the ingestion pipeline (which only writes what CalicoTab actually published) -- this is our
own derived analysis, stored in `BreakPrediction`, never mixed with the OFFICIAL `Break` rows
the scraper writes once the tournament publishes its real break.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.break_predictor import BreakAssessment, build_break_report
from app.models import BreakCategory, BreakPrediction, Round
from app.models.enums import RoundStage
from app.repositories.upsert import upsert_by_natural_key
from app.services.ranking_service import (
    get_latest_completed_round_seq,
    get_standings,
    get_total_preliminary_rounds,
)


async def recompute_break_predictions(
    session: AsyncSession,
    tournament_id: int,
    break_category_id: int,
    *,
    num_simulations: int = 2000,
) -> list[BreakAssessment]:
    category = await session.get(BreakCategory, break_category_id)
    if category is None or category.break_size is None:
        return []

    latest_round_seq = await get_latest_completed_round_seq(session, tournament_id)
    if latest_round_seq is None:
        return []
    total_rounds = await get_total_preliminary_rounds(session, tournament_id)
    rounds_remaining = max(total_rounds - latest_round_seq, 0)

    latest_round_id = (
        await session.execute(
            select(Round.id).where(
                Round.tournament_id == tournament_id,
                Round.stage == RoundStage.PRELIMINARY,
                Round.seq == latest_round_seq,
            )
        )
    ).scalar_one()

    standings = await get_standings(
        session,
        tournament_id,
        as_of_round_seq=latest_round_seq,
        break_category_id=break_category_id,
    )
    if not standings:
        return []

    report = build_break_report(
        standings,
        break_size=category.break_size,
        rounds_remaining=rounds_remaining,
        num_simulations=num_simulations,
    )

    for assessment in report:
        await upsert_by_natural_key(
            session,
            BreakPrediction,
            lookup={
                "tournament_id": tournament_id,
                "break_category_id": break_category_id,
                "team_id": assessment.team_id,
                "as_of_round_id": latest_round_id,
            },
            values={
                "status": assessment.status,
                "probability": assessment.probability,
                "projected_rank": assessment.projected_rank,
                "points_needed": (
                    {"points": assessment.points_needed_for_safety}
                    if assessment.points_needed_for_safety is not None
                    else None
                ),
            },
        )

    return report
