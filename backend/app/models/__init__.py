"""SQLAlchemy models package.

Every model module is imported here so that (a) ``Base.metadata`` is fully populated for
Alembic autogenerate / ``create_all`` and (b) callers can simply do ``from app import models``.
"""

from app.db.base import Base
from app.models.betting import BetMarket, LeaderboardEntry, Prediction, User
from app.models.breaks import AdjudicatorBreak, Break, BreakPrediction
from app.models.participants import (
    Adjudicator,
    BreakCategory,
    Institution,
    Speaker,
    SpeakerCategory,
    SpeakerCategoryLink,
    Team,
    TeamBreakCategory,
)
from app.models.rounds import (
    Debate,
    DebateAdjudicator,
    DebateTeam,
    Result,
    Room,
    Round,
    SpeakerScore,
)
from app.models.scraping import ChangeEvent, ScrapeLog
from app.models.tournament import Tournament

__all__ = [
    "Base",
    "Tournament",
    "Institution",
    "BreakCategory",
    "SpeakerCategory",
    "Team",
    "TeamBreakCategory",
    "Speaker",
    "SpeakerCategoryLink",
    "Adjudicator",
    "Round",
    "Room",
    "Debate",
    "DebateTeam",
    "SpeakerScore",
    "DebateAdjudicator",
    "Result",
    "Break",
    "BreakPrediction",
    "AdjudicatorBreak",
    "User",
    "BetMarket",
    "Prediction",
    "LeaderboardEntry",
    "ScrapeLog",
    "ChangeEvent",
]
