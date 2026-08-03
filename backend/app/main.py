import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import (
    access_passes,
    admin,
    archive,
    auth,
    betting,
    breaks,
    dashboard,
    leaderboard,
    participants,
    prizes,
    rounds,
    standings,
    tournaments,
    transfers,
)
from app.core.config import get_settings
from app.tasks.autoscrape import autoscrape_loop

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Owns the in-process periodic scraper (see app.tasks.autoscrape for why it lives in the
    API process rather than in Celery). Cancelled cleanly on shutdown so a reload/redeploy
    doesn't leave a half-finished scrape holding a database session."""
    task: asyncio.Task | None = None
    if settings.autoscrape_enabled:
        task = asyncio.create_task(autoscrape_loop())
        logging.getLogger(__name__).info(
            "autoscrape enabled: every %ss", settings.scrape_interval_seconds
        )
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API for the Claim debate tournament friendly-betting platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_logger = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all so unexpected errors become a JSON 500 *inside* the middleware stack.

    Without this, an unhandled exception propagates past CORSMiddleware and the bare 500 ships
    without CORS headers -- the browser then reports a network failure ("Failed to fetch")
    instead of the real 500, which is how the debate-detail crash surfaced as a silently
    unresponsive page instead of a visible server error.
    """
    _logger.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(tournaments.router, prefix=API_PREFIX)
app.include_router(participants.router, prefix=API_PREFIX)
app.include_router(rounds.router, prefix=API_PREFIX)
app.include_router(standings.router, prefix=API_PREFIX)
app.include_router(breaks.router, prefix=API_PREFIX)
app.include_router(betting.router, prefix=API_PREFIX)
app.include_router(leaderboard.router, prefix=API_PREFIX)
app.include_router(dashboard.router, prefix=API_PREFIX)
app.include_router(prizes.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(transfers.router, prefix=API_PREFIX)
app.include_router(access_passes.router, prefix=API_PREFIX)
app.include_router(archive.router, prefix=API_PREFIX)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
