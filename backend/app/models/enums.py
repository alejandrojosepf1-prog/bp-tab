import enum


class TournamentStatus(str, enum.Enum):
    UPCOMING = "upcoming"
    IN_PROGRESS = "in_progress"
    BREAK_PENDING = "break_pending"
    ELIMINATIONS = "eliminations"
    COMPLETED = "completed"


class RoundStage(str, enum.Enum):
    PRELIMINARY = "preliminary"
    ELIMINATION = "elimination"


class RoundStatus(str, enum.Enum):
    DRAFT = "draft"
    RELEASED = "released"
    COMPLETED = "completed"


class DebateStatus(str, enum.Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class BPPosition(str, enum.Enum):
    """A team's position in a British Parliamentary debate."""

    OPENING_GOVERNMENT = "OG"
    OPENING_OPPOSITION = "OO"
    CLOSING_GOVERNMENT = "CG"
    CLOSING_OPPOSITION = "CO"


class SpeakerRole(str, enum.Enum):
    """Standard BP speaker roles, two per team."""

    PM = "PM"
    DPM = "DPM"
    LO = "LO"
    DLO = "DLO"
    MG = "MG"
    GW = "GW"
    MO = "MO"
    OW = "OW"


class JudgeRole(str, enum.Enum):
    CHAIR = "chair"
    PANELLIST = "panellist"
    TRAINEE = "trainee"


class BreakStatus(str, enum.Enum):
    PROJECTED = "projected"
    CONFIRMED = "confirmed"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class BetType(str, enum.Enum):
    CHAMPION = "champion"
    TOP_N_BREAK = "top_n_break"
    TOP_N_SPEAKERS = "top_n_speakers"
    ROUND_WINNER = "round_winner"
    HEAD_TO_HEAD = "head_to_head"
    BREAKOUT_TEAM = "breakout_team"
    BEST_INSTITUTION = "best_institution"


class BetMarketStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class PredictionStatus(str, enum.Enum):
    OPEN = "open"
    LOCKED = "locked"
    SETTLED = "settled"


class ScrapeStatus(str, enum.Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ScrapeStrategy(str, enum.Enum):
    API = "api"
    HTML_VUEDATA = "html_vuedata"
    HTML_LIST = "html_list"


class ChangeType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
