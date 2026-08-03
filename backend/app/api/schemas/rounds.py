from pydantic import BaseModel, ConfigDict

from app.api.schemas.participants import SpeakerOut, TeamOut
from app.models.enums import (
    BPPosition,
    DebateStatus,
    JudgeRole,
    RoundStage,
    RoundStatus,
    SpeakerRole,
)


class RoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int
    name: str
    stage: RoundStage
    status: RoundStatus
    # Mirrored from the tournament's public /motions/ page -- NULL until that round's motion is
    # released. Lets the betting UI show what's being debated inline instead of sending people
    # to the tab in another tab.
    motion_text: str | None = None
    info_slide: str | None = None


class RoomOut(BaseModel):
    name: str


class DebateTeamSummaryOut(BaseModel):
    team: TeamOut
    position: BPPosition
    rank_in_debate: int | None
    team_points: int | None


class DebateSummaryOut(BaseModel):
    id: int
    room: RoomOut | None
    status: DebateStatus
    teams: list[DebateTeamSummaryOut]


class DebateSpeakerScoreOut(BaseModel):
    speaker: SpeakerOut
    role: SpeakerRole
    score: float | None
    is_iron: bool


class DebateTeamDetailOut(BaseModel):
    team: TeamOut
    position: BPPosition
    rank_in_debate: int | None
    team_points: int | None
    speaker_points_total: float | None
    speakers: list[DebateSpeakerScoreOut]


class DebateAdjudicatorOut(BaseModel):
    adjudicator_id: int
    name: str
    role: JudgeRole


class DebateDetailOut(BaseModel):
    id: int
    round: RoundOut
    room: RoomOut | None
    status: DebateStatus
    motion_text: str | None
    ballot_source_url: str | None
    video_url: str | None
    teams: list[DebateTeamDetailOut]
    adjudicators: list[DebateAdjudicatorOut]
