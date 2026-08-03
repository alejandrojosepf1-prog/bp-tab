import datetime

from pydantic import BaseModel


class LeaderboardUserOut(BaseModel):
    id: int
    display_name: str


class LeaderboardEntryOut(BaseModel):
    user: LeaderboardUserOut
    # Net profit/loss (payout minus stake, in fictional USD) across every settled prediction on
    # THIS tournament's markets -- can go negative, unlike the user's wallet balance for this
    # tournament (TournamentBalance / GET /tournaments/{id}/me/balance). No real money involved
    # anywhere -- see app.domain.odds and app.services.betting_service.
    total_points: float
    rank: int
    computed_at: datetime.datetime


class GlobalLeaderboardEntryOut(BaseModel):
    user: LeaderboardUserOut
    # Summed net profit/loss across every tournament this user has a leaderboard entry in --
    # see app.services.global_leaderboard_service. Can go negative.
    total_points: float
    tournaments_played: int
    # Play-token wallet summed across every tournament this user has a TournamentBalance in --
    # shown alongside net profit since a balance also reflects tokens still tied up in OPEN
    # predictions and any ROI carryover, not just settled skill.
    balance: float
    rank: int
