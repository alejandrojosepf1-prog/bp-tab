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


class MotionCategory(str, enum.Enum):
    """CMUDE 2026 manual §2.7 taxonomy for what KIND of motion a round's is, independent of the
    motion's actual text/topic. Ground truth is loaded onto `Round.motion_category` by an admin
    BEFORE the motion is revealed (the committee already knows it); `MOTION_TYPE` bets guess
    which of these 9 it'll turn out to be."""

    POLICY = "policy"  # "Esta Casa [haría X]"
    POLICY_SHOULD = "policy_should"  # "Esta Casa considera que [X] debería..."
    VALUE_JUDGMENT = "value_judgment"  # "Esta Casa considera que [X]" (análisis)
    SUPPORT_OPPOSE = "support_oppose"  # "Esta Casa apoya / se opone a [X]"
    REGRET = "regret"  # "Esta Casa lamenta [X]"
    PREFERENCE = "preference"  # "Esta Casa prefiere [X]"
    PREDICTION = "prediction"  # "Esta Casa predice [X]"
    HOPE = "hope"  # "Esta Casa Espera [X]"
    ACTOR = "actor"  # "Esta Casa, siendo [A], haría [X]"


class BetType(str, enum.Enum):
    CHAMPION = "champion"
    ROUND_WINNER = "round_winner"
    ROUND_FULL_CALL = "round_full_call"
    TOP_SPEAKER_POSITION = "top_speaker_position"
    TEAM_BREAK = "team_break"
    # Bet on which of two teams in the SAME debate finishes ranked higher -- distinct from the
    # retired global HEAD_TO_HEAD below (which compared final tournament standings, not a
    # specific drawn room). Round-scoped like ROUND_WINNER/ROUND_FULL_CALL.
    ROUND_HEAD_TO_HEAD = "round_head_to_head"
    # Guess the round's MotionCategory before the motion is revealed -- fixed-odds (not
    # pari-mutuel, see odds_service.MOTION_TYPE_FIXED_ODDS), unlike every bet type above.
    MOTION_TYPE = "motion_type"

    # Retired from the admin "create market" UI in favor of the five types above, but kept as
    # valid enum members -- and their pricing/settlement code kept working -- so any market of
    # these types created before the redesign (and its predictions) keeps resolving correctly.
    # Never offered for NEW markets going forward.
    TOP_N_BREAK = "top_n_break"
    TOP_N_SPEAKERS = "top_n_speakers"
    HEAD_TO_HEAD = "head_to_head"
    BREAKOUT_TEAM = "breakout_team"
    BEST_INSTITUTION = "best_institution"
    # Bet on the EXACT pair of teams that advances out of a 4-team out-round debate. Retired in
    # favor of folding this into ROUND_WINNER itself (a `team_ids` payload on an elimination
    # debate now prices/settles the same proposition -- see betting_service._entity_key,
    # odds_service.quote_odds, and domain.bet_outcomes._round_winner). Kept here only because
    # this is a native Postgres enum type and no market of this type was ever created, so there
    # is no data to migrate -- same "kept but unreferenced" treatment as the block above.
    ROUND_ADVANCING_PAIR = "round_advancing_pair"


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


class PrizeEventType(str, enum.Enum):
    # Admin queues named awards with their own amount each; resolving credits them all at once.
    MANUAL_AWARD = "manual_award"
    # Users buy in with tickets; resolving draws winners weighted by ticket count.
    RAFFLE = "raffle"
    # No entries until resolve -- resolving itself computes who qualified (placed at least one
    # bet on the tournament in the event's window) and credits every qualifying user a flat bonus.
    ACTIVITY_BONUS = "activity_bonus"


class PrizeEventStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class TransactionType(str, enum.Enum):
    """Ledger entry kind for app.models.transactions.Transaction. A P2P transfer always writes
    TWO rows (one per side) so `SELECT ... WHERE user_id = X` alone reconstructs that user's full
    history -- no join needed to see "who sent me what." Deliberately scoped to transfers only
    for now (see Transaction's docstring): stake/payout/prize movements don't write here yet."""

    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
