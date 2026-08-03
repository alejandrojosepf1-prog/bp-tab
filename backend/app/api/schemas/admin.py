import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import MotionCategory, ScrapeStatus, ScrapeStrategy, UserRole


class ScrapeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    status: ScrapeStatus
    strategy_used: ScrapeStrategy
    pages_fetched: int
    entities_created: int
    entities_updated: int
    error_message: str | None


class AdminUserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None


class PendingEliminationTeamOut(BaseModel):
    team_id: int
    team_name: str


class PendingEliminationDebateOut(BaseModel):
    """One elimination-round debate whose outcome Tabbycat hasn't published, surfaced so an
    admin can fill it in by hand (see app.services.manual_results_service)."""

    debate_id: int
    tournament_id: int
    round_id: int
    round_name: str
    is_final: bool
    teams: list[PendingEliminationTeamOut]


class ManualEliminationResultIn(BaseModel):
    """Exactly one of the two fields must be set, matching whether the target debate is the
    Grand Final (champion_team_id) or an earlier elimination round (advancing_team_ids)."""

    champion_team_id: int | None = None
    advancing_team_ids: list[int] | None = None

    @model_validator(mode="after")
    def _exactly_one_field(self) -> "ManualEliminationResultIn":
        if (self.champion_team_id is None) == (self.advancing_team_ids is None):
            raise ValueError(
                "provide exactly one of champion_team_id or advancing_team_ids"
            )
        return self


class RoundMotionCategoryPatch(BaseModel):
    motion_category: MotionCategory | None = None


class RoundMotionCategoryOut(BaseModel):
    """Admin-only view of a round's motion-category ground truth -- deliberately separate from
    the public RoundOut schema, which never exposes this field (it would leak the answer to the
    MOTION_TYPE market before the motion is revealed)."""

    round_id: int
    motion_category: MotionCategory | None


class MarketPayoutSpreadOut(BaseModel):
    market_id: int
    market_label: str
    pool_total: float
    worst_case: float
    best_case: float


class CircuitInstitutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    region: str | None


class CircuitReviewItemOut(BaseModel):
    """One tournament-scoped Institution row whose current circuit-identity link came from an
    unconfirmed fuzzy match (see app.services.circuit_curation_service)."""

    institution_id: int
    tournament_id: int
    institution_name: str
    institution_code: str
    matched_circuit_institution: CircuitInstitutionOut


class CircuitInstitutionResolveIn(BaseModel):
    """Exactly one of the two ways to resolve a review item: point at an existing circuit
    identity, or name a brand-new one (region optional either way)."""

    circuit_institution_id: int | None = None
    new_institution_name: str | None = None
    new_institution_region: str | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "CircuitInstitutionResolveIn":
        if (self.circuit_institution_id is None) == (self.new_institution_name is None):
            raise ValueError(
                "provide exactly one of circuit_institution_id or new_institution_name"
            )
        return self


class UnassignedTeamOut(BaseModel):
    """A team the automatic prefix heuristic (_match_institution_by_name_prefix) couldn't link
    to any institution in its own tournament -- surfaced so an admin can assign one by hand."""

    team_id: int
    tournament_id: int
    team_name: str


class GameEconomyOut(BaseModel):
    total_staked_open: float
    total_staked_settled: float
    total_paid_out: float
    net_token_inflation: float
    tokens_in_circulation: float
    open_predictions_count: int
    settled_predictions_count: int
    active_bettors_count: int
    payout_spread: list[MarketPayoutSpreadOut]
    payout_spread_worst_case_total: float
    payout_spread_best_case_total: float
