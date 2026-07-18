import datetime

from pydantic import BaseModel


class LeaderboardUserOut(BaseModel):
    id: int
    display_name: str


class LeaderboardEntryOut(BaseModel):
    user: LeaderboardUserOut
    # Fictional USD ("dólares ficticios apostados") accumulated across every settled
    # prediction -- no real money involved, see app.domain.scoring.
    total_points: float
    rank: int
    computed_at: datetime.datetime
