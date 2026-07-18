"""Pure British Parliamentary ranking rules.

Nothing in this module touches SQLAlchemy or the database -- it operates on plain dataclasses
so the tie-break cascade (the trickiest, most bug-prone part of any BP tab) can be unit tested
in isolation, the same way a debating society would verify it by hand against worked examples.
"""

from dataclasses import dataclass, field

# BP scores each of the 4 teams in a debate 3/2/1/0 points by placement (1st/2nd/3rd/4th).
BP_POINTS_BY_RANK: dict[int, int] = {1: 3, 2: 2, 3: 1, 4: 0}


@dataclass(frozen=True)
class DebateTeamRecord:
    """One team's result in one debate -- the minimal input the ranking algorithm needs."""

    team_id: int
    rank_in_debate: int  # 1..4
    speaker_points: float | None = None  # None if the tournament withholds speaker scores


@dataclass(frozen=True)
class TeamStanding:
    team_id: int
    rank: int
    team_points: int
    total_speaker_points: float
    firsts: int
    seconds: int
    thirds: int
    fourths: int
    debates_played: int


def team_points_for_rank(rank_in_debate: int) -> int:
    try:
        return BP_POINTS_BY_RANK[rank_in_debate]
    except KeyError as exc:
        raise ValueError(f"rank_in_debate must be 1-4, got {rank_in_debate}") from exc


@dataclass
class _Accumulator:
    team_id: int
    team_points: int = 0
    total_speaker_points: float = 0.0
    firsts: int = 0
    seconds: int = 0
    thirds: int = 0
    fourths: int = 0
    debates_played: int = 0
    placements: list[int] = field(default_factory=list)


def compute_standings(records: list[DebateTeamRecord]) -> list[TeamStanding]:
    """Aggregate per-debate results into a ranked table.

    Tie-break cascade, in order (the standard BP convention):
      1. Team points (sum of 3/2/1/0 across debates)
      2. Total speaker points (sum of both speakers' scores across debates) -- skipped
         gracefully if speaker points aren't available yet (tournament hasn't released them)
      3. Number of 1st-place finishes, then 2nd-place finishes (rewards more firsts over
         more seconds when points and speaks are tied)
      4. team_id, purely for a stable/deterministic order -- never meant to reflect merit;
         a true unresolved tie should be surfaced to the tournament's own tab, not invented here
    """
    accumulators: dict[int, _Accumulator] = {}
    speaker_points_known = True

    for record in records:
        acc = accumulators.setdefault(record.team_id, _Accumulator(team_id=record.team_id))
        acc.team_points += team_points_for_rank(record.rank_in_debate)
        acc.debates_played += 1
        acc.placements.append(record.rank_in_debate)
        if record.speaker_points is None:
            speaker_points_known = False
        else:
            acc.total_speaker_points += record.speaker_points
        if record.rank_in_debate == 1:
            acc.firsts += 1
        elif record.rank_in_debate == 2:
            acc.seconds += 1
        elif record.rank_in_debate == 3:
            acc.thirds += 1
        elif record.rank_in_debate == 4:
            acc.fourths += 1

    def sort_key(acc: _Accumulator) -> tuple:
        return (
            -acc.team_points,
            -acc.total_speaker_points if speaker_points_known else 0,
            -acc.firsts,
            -acc.seconds,
            acc.team_id,
        )

    ordered = sorted(accumulators.values(), key=sort_key)

    return [
        TeamStanding(
            team_id=acc.team_id,
            rank=i + 1,
            team_points=acc.team_points,
            total_speaker_points=acc.total_speaker_points,
            firsts=acc.firsts,
            seconds=acc.seconds,
            thirds=acc.thirds,
            fourths=acc.fourths,
            debates_played=acc.debates_played,
        )
        for i, acc in enumerate(ordered)
    ]
