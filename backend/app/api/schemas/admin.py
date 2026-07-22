import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import ScrapeStatus, ScrapeStrategy, UserRole


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


class MarketExposureOut(BaseModel):
    market_id: int
    market_label: str
    pool_total: float
    worst_case: float
    best_case: float


class HouseFinanceOut(BaseModel):
    total_staked_open: float
    total_staked_settled: float
    total_paid_out: float
    realized_net_profit: float
    exposure: list[MarketExposureOut]
    exposure_worst_case_total: float
    exposure_best_case_total: float
