"""In-process periodic scraper, so tournaments stay up to date with no admin clicking anything.

Why this exists alongside the Celery beat schedule in `celery_app.py`: this deployment has no
Redis and no Celery worker/beat process (see the comments at the top of `render.yaml` -- the free
Render + Neon setup deliberately skips the broker), which means the beat schedule never actually
fires in production. Until now the ONLY thing that refreshed a tournament was an admin manually
hitting "Forzar scraping", so markets went stale and finished rounds never auto-settled.

This runs the exact same `scrape_tournament_async` the Celery task and the admin button already
call -- only the trigger differs -- as a plain asyncio task owned by the FastAPI app's lifespan.
Nothing here is Celery-aware; if a real broker is ever added, set `autoscrape_enabled=false` and
let beat drive it instead so the two can't both scrape the same tournament.

Deliberately sequential: tournaments are scraped one after another rather than concurrently, to
stay polite to the upstream Tabbycat host (which is someone else's server, often a small one) and
to keep peak memory flat on a free-tier instance.
"""

import asyncio
import logging

from app.core.config import get_settings
from app.tasks.scrape_tasks import scrape_all_active_tournaments_async, scrape_tournament_async

logger = logging.getLogger(__name__)


async def _run_one_cycle() -> None:
    tournament_ids = await scrape_all_active_tournaments_async()
    if not tournament_ids:
        logger.debug("autoscrape: no active tournaments")
        return
    for tournament_id in tournament_ids:
        try:
            result = await scrape_tournament_async(tournament_id)
            logger.info("autoscrape: scraped tournament %s -> %s", tournament_id, result)
        except Exception:
            # One tournament failing (upstream 500, tab taken offline, schema change...) must
            # never stop the others, nor kill the loop -- the next cycle simply retries.
            logger.exception("autoscrape: tournament %s failed", tournament_id)


async def autoscrape_loop() -> None:
    """Forever: scrape every active tournament, then sleep `scrape_interval_seconds`.

    Cancelled by the lifespan handler on shutdown. Any non-cancellation error is swallowed and
    logged so a single bad cycle can't take the loop (and therefore all auto-updating) down for
    the remaining uptime of the process.
    """
    settings = get_settings()
    # Don't scrape the instant the process boots: on Render a deploy (or a free-tier cold start)
    # restarts the app, and hammering the upstream tab on every restart is both rude and useless
    # when the previous instance just scraped moments ago.
    await asyncio.sleep(settings.autoscrape_startup_delay_seconds)
    while True:
        try:
            await _run_one_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("autoscrape: cycle failed")
        await asyncio.sleep(settings.scrape_interval_seconds)
