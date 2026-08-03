from pydantic import BaseModel, ConfigDict

from app.models.enums import MotionCategory


class CircuitInstitutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    region: str | None


class InstitutionTournamentAppearanceOut(BaseModel):
    """One tournament a circuit institution's per-tournament Institution row was matched to --
    the cross-tournament "history" that's the whole point of the circuit identity layer."""

    tournament_name: str
    tournament_slug: str
    tournament_year: int | None
    team_names: list[str]
    was_champion: bool


class CircuitInstitutionDetailOut(CircuitInstitutionOut):
    appearances: list[InstitutionTournamentAppearanceOut]


class MotionEntryOut(BaseModel):
    tournament_name: str
    tournament_slug: str
    tournament_year: int | None
    round_name: str
    motion_text: str
    motion_category: MotionCategory | None
