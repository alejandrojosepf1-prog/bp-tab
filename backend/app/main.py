from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
