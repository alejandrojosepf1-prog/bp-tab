"""SQLAlchemy models package.

Every model module is imported here so that (a) ``Base.metadata`` is fully populated for
Alembic autogenerate / ``create_all`` and (b) callers can simply do ``from app import models``.
"""

from app.db.base import Base
from app.models.betting import (
    BetMarket,
    LeaderboardEntry,
    OddsSnapshot,
    Prediction,
    TournamentBalance,
    User,
)
from app.models.breaks import AdjudicatorBreak, Break, BreakPrediction
from app.models.circuit import (
    CircuitInstitution,
    CircuitInstitutionAlias,
    CircuitPerson,
    CircuitPersonAlias,
)
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
from app.models.prizes import PrizeEntry, PrizeEvent
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
from app.models.transactions import Transaction

__all__ = [
    "Base",
    "Tournament",
    "CircuitInstitution",
    "CircuitInstitutionAlias",
    "CircuitPerson",
    "CircuitPersonAlias",
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
    "TournamentBalance",
    "OddsSnapshot",
    "PrizeEvent",
    "PrizeEntry",
    "ScrapeLog",
    "ChangeEvent",
    "Transaction",
]
