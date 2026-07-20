import datetime

from pydantic import BaseModel


class LeaderboardUserOut(BaseModel):
    id: int
    display_name: str


class LeaderboardEntryOut(BaseModel):
    user: LeaderboardUserOut
    # Net profit/loss (payout minus stake, in fictional USD) across every settled prediction on
    # THIS tournament's markets -- can go negative, unlike the user's overall wallet balance
    # (User.balance / GET /auth/me), which is global across every tournament. No real money
    # involved anywhere -- see app.domain.odds and app.services.betting_service.
    total_points: float
    rank: int
    computed_at: datetime.datetime
