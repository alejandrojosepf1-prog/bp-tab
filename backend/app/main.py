import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import (
    admin,
    auth,
    betting,
    breaks,
    dashboard,
    leaderboard,
    participants,
    rounds,
    standings,
    tournaments,
)
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API for the BP debate tournament friendly-betting platform.",
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
app.include_router(admin.router, prefix=API_PREFIX)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
