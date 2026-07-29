from pydantic import BaseModel, ConfigDict

from app.api.schemas.participants import TeamOut


class BreakCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    is_general: bool
    break_size: int | None


class BreakCategoryUpdate(BaseModel):
    # Tabbycat doesn't reliably expose "how many teams break" as structured data before the
    # break is actually published, so this has to come from an admin who knows the announced
    # break size -- see app.services.ingestion._ensure_general_break_category and
    # app.services.break_service (break_size is required to price/predict anything).
    break_size: int


class BreakAssessmentOut(BaseModel):
    team: TeamOut
    status: str
    probability: float
    projected_rank: int | None
    points_needed_for_safety: int | None


class BreakEntryOut(BaseModel):
    team: TeamOut
    rank: int
