"""Celery tasks that drive the whole "scrape -> ingest -> recompute -> settle" cycle.

`scrape_all_active_tournaments` is the periodic (beat) entry point; it just fans out one
`scrape_tournament` task per active tournament so a slow or failing tournament never blocks
the others. `scrape_tournament` is also what the admin panel's "Forzar scraping" button calls
directly (same task, just triggered on demand instead of by the schedule).

The actual async logic lives in module-level `_async` functions that accept an injectable
`session_factory`, purely so tests can point it at a SQLite session instead of the real
Postgres-backed `AsyncSessionLocal` -- the Celery task wrappers always use the real one.
"""

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models import BreakCategory, Debate, Tournament
from app.models.betting import BetMarket
from app.models.enums import BetMarketStatus
from app.scraper.orchestrator import TournamentScraper
from app.services.betting_service import (
    auto_close_pretournament_markets,
    settle_market,
    settle_pending_sub_bets,
)
from app.services.break_service import recompute_break_predictions
from app.services.ingestion import IngestionService
from app.services.tournament_service import refresh_tournament_status
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


async def scrape_tournament_async(
    tournament_id: int, *, session_factory: SessionFactory = AsyncSessionLocal
) -> dict:
    async with session_factory() as session:
        tournament = await session.get(Tournament, tournament_id)
        if tournament is None or not tournament.is_active:
            return {"tournament_id": tournament_id, "skipped": True}

        known_debate_external_ids = frozenset(
            (
                await session.execute(
                    select(Debate.external_id).where(Debate.tournament_id == tournament.id)
                )
            )
            .scalars()
            .all()
        )

        scraper = TournamentScraper(tournament.source_base_url, tournament.source_slug)
        try:
            tournament.api_available = await scraper.check_api_available()
            snapshot = await scraper.scrape(known_debate_external_ids=known_debate_external_ids)
        finally:
            await scraper.close()

        log = await IngestionService(session).ingest(tournament, snapshot)
        await refresh_tournament_status(session, tournament)
        await auto_close_pretournament_markets(session, tournament)
        await _recompute_break_predictions_for_tournament(session, tournament.id)
        await _settle_resolvable_markets(session, tournament.id)
        await settle_pending_sub_bets(session, tournament.id)

        await session.commit()
        return {
            "tournament_id": tournament_id,
            "entities_created": log.entities_created,
            "entities_updated": log.entities_updated,
            "new_debates": len(snapshot.ballots),
        }


async def _recompute_break_predictions_for_tournament(
    session: AsyncSession, tournament_id: int
) -> None:
    categories = (
        (
            await session.execute(
                select(BreakCategory).where(
                    BreakCategory.tournament_id == tournament_id,
                    BreakCategory.break_size.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for category in categories:
        await recompute_break_predictions(session, tournament_id, category.id)


async def _settle_resolvable_markets(session: AsyncSession, tournament_id: int) -> None:
    markets = (
        (
            await session.execute(
                select(BetMarket).where(
                    BetMarket.tournament_id == tournament_id,
                    BetMarket.status != BetMarketStatus.SETTLED,
                )
            )
        )
        .scalars()
        .all()
    )
    for market in markets:
        try:
            await settle_market(session, market)
        except Exception:
            logger.exception("failed to settle bet_market %s", market.id)


async def scrape_all_active_tournaments_async(
    *, session_factory: SessionFactory = AsyncSessionLocal
) -> list[int]:
    async with session_factory() as session:
        ids = (
            (await session.execute(select(Tournament.id).where(Tournament.is_active.is_(True))))
            .scalars()
            .all()
        )
    return list(ids)


@celery_app.task(name="app.tasks.scrape_tasks.scrape_tournament", bind=True, max_retries=3)
def scrape_tournament(self, tournament_id: int) -> dict:  # type: ignore[no-untyped-def]
    try:
        return asyncio.run(scrape_tournament_async(tournament_id))
    except Exception as exc:
        logger.exception("scrape_tournament failed for tournament_id=%s", tournament_id)
        raise self.retry(exc=exc, countdown=30) from exc


@celery_app.task(name="app.tasks.scrape_tasks.scrape_all_active_tournaments")
def scrape_all_active_tournaments() -> None:
    tournament_ids = asyncio.run(scrape_all_active_tournaments_async())
    for tournament_id in tournament_ids:
        scrape_tournament.delay(tournament_id)
