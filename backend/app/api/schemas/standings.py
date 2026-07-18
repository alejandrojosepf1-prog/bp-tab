from pydantic import BaseModel

from app.api.schemas.participants import TeamOut


class TeamStandingOut(BaseModel):
    team: TeamOut
    rank: int
    team_points: int
    total_speaker_points: float
    firsts: int
    seconds: int
    thirds: int
    fourths: int
    debates_played: int
