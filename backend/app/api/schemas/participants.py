from pydantic import BaseModel, ConfigDict


class InstitutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    region: str | None


class SpeakerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    team_id: int | None
    categories: list[str]


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: int
    name: str
    emoji: str | None
    institution: InstitutionOut | None
    speakers: list[SpeakerOut]


class AdjudicatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: int
    name: str
    institution: InstitutionOut | None
    is_independent: bool
    broke: bool
