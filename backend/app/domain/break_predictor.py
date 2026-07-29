"""Break Predictor: classify each team's break chances and estimate a probability.

Two independent pieces, deliberately kept separate because they answer different questions:

1. ``classify_status`` -- a RIGOROUS, deterministic "safe / alive / eliminated" verdict, using
   the same points-ceiling/floor logic sports leagues use for "clinched" / "eliminated from
   contention" standings. No randomness, no assumptions about how remaining rounds will be
   drawn -- just "is it still mathematically possible".

2. ``simulate_break_probabilities`` -- a lightweight Monte Carlo ESTIMATE of P(breaking) for
   teams that are merely "alive", used to show a friendly percentage on the dashboard. This
   necessarily makes a simplifying assumption (each team's remaining-round placements are drawn
   independently from its own empirical placement distribution so far) rather than simulating
   actual 4-team-per-room BP draws where placements within a debate are not independent -- that
   full simulation is out of scope for a friendly predictor. Documented here so nobody mistakes
   the probability for a rigorous guarantee the way ``classify_status`` is.
"""

import random
from collections import defaultdict
from dataclasses import dataclass

from app.domain.ranking import BP_POINTS_BY_RANK, TeamStanding

POINTS_PER_ROUND_MAX = max(BP_POINTS_BY_RANK.values())


@dataclass(frozen=True)
class BreakAssessment:
    team_id: int
    status: str  # "safe" | "alive" | "eliminated"
    probability: float
    projected_rank: int | None
    points_needed_for_safety: int | None


def classify_status(
    team_points: int, *, other_teams_points: list[int], rounds_remaining: int, break_size: int
) -> str:
    """Rigorous classification using points ceiling/floor -- see module docstring."""
    ceiling_others = [p + POINTS_PER_ROUND_MAX * rounds_remaining for p in other_teams_points]
    floor_self = team_points
    ceiling_self = team_points + POINTS_PER_ROUND_MAX * rounds_remaining

    teams_that_could_still_beat_floor = sum(1 for c in ceiling_others if c > floor_self)
    if teams_that_could_still_beat_floor < break_size:
        return "safe"

    teams_already_certainly_ahead = sum(1 for p in other_teams_points if p > ceiling_self)
    if teams_already_certainly_ahead >= break_size:
        return "eliminated"

    return "alive"


def points_needed_for_safety(
    team_points: int, *, other_teams_points: list[int], rounds_remaining: int, break_size: int
) -> int | None:
    """How many more total points this team would need (on top of its current total) to be
    mathematically SAFE right now, assuming it wins the rest and nothing else changes about the
    rivals already counted. Returns None if already safe or if rounds_remaining is 0 (nothing to
    project forward)."""
    if rounds_remaining <= 0:
        return None
    for extra in range(0, POINTS_PER_ROUND_MAX * rounds_remaining + 1):
        hypothetical = team_points + extra
        ceiling_others = [p + POINTS_PER_ROUND_MAX * rounds_remaining for p in other_teams_points]
        if sum(1 for c in ceiling_others if c > hypothetical) < break_size:
            return extra
    return None


def build_break_report(
    standings: list[TeamStanding],
    *,
    break_size: int,
    rounds_remaining: int,
    num_simulations: int = 2000,
) -> list[BreakAssessment]:
    """Full per-team assessment for a break category, combining the rigorous classification
    with a simulated probability for the teams still genuinely in contention."""
    points_by_team = {s.team_id: s.team_points for s in standings}
    placement_history = placement_history_by_team(standings)

    assessments = []
    for team in standings:
        others_points = [p for tid, p in points_by_team.items() if tid != team.team_id]
        status = classify_status(
            team.team_points,
            other_teams_points=others_points,
            rounds_remaining=rounds_remaining,
            break_size=break_size,
        )
        if status == "safe":
            probability = 1.0
        elif status == "eliminated":
            probability = 0.0
        else:
            probability = _simulate_probability(
                team.team_id,
                points_by_team=points_by_team,
                placement_history=placement_history,
                rounds_remaining=rounds_remaining,
                break_size=break_size,
                num_simulations=num_simulations,
            )
        assessments.append(
            BreakAssessment(
                team_id=team.team_id,
                status=status,
                probability=probability,
                projected_rank=team.rank,
                points_needed_for_safety=points_needed_for_safety(
                    team.team_points,
                    other_teams_points=others_points,
                    rounds_remaining=rounds_remaining,
                    break_size=break_size,
                )
                if status != "safe"
                else None,
            )
        )
    return assessments


def placement_history_by_team(standings: list[TeamStanding]) -> dict[int, dict[int, int]]:
    """A team's own {rank: times_achieved} distribution, from what compute_standings tracked."""
    history = {}
    for s in standings:
        history[s.team_id] = {1: s.firsts, 2: s.seconds, 3: s.thirds, 4: s.fourths}
    return history


def _draw_round_points(rank_counts: dict[int, int], rng: random.Random) -> int:
    total = sum(rank_counts.values())
    if total == 0:
        # No history yet (e.g. before Round 1) -- assume an even chance of any placement.
        return BP_POINTS_BY_RANK[rng.randint(1, 4)]
    roll = rng.uniform(0, total)
    cumulative = 0.0
    for rank, count in rank_counts.items():
        cumulative += count
        if roll <= cumulative:
            return BP_POINTS_BY_RANK[rank]
    return BP_POINTS_BY_RANK[4]


def _simulate_probability(
    team_id: int,
    *,
    points_by_team: dict[int, int],
    placement_history: dict[int, dict[int, int]],
    rounds_remaining: int,
    break_size: int,
    num_simulations: int,
) -> float:
    rng = random.Random(f"break-predictor:{team_id}")
    breaks = 0
    for _ in range(num_simulations):
        final_points = dict(points_by_team)
        for tid in final_points:
            history = placement_history.get(tid, {})
            for _round in range(rounds_remaining):
                final_points[tid] += _draw_round_points(history, rng)
        ranked = sorted(final_points.items(), key=lambda kv: (-kv[1], kv[0]))
        breaking_ids = {tid for tid, _ in ranked[:break_size]}
        if team_id in breaking_ids:
            breaks += 1
    return breaks / num_simulations


def simulate_rank_distribution(
    team_id: int,
    *,
    points_by_team: dict[int, int],
    placement_history: dict[int, dict[int, int]],
    rounds_remaining: int,
    num_simulations: int,
) -> dict[int, float]:
    """P(this team finishes in EXACTLY final rank r), for every r it was ever simulated to land
    on -- prices `team_break`'s optional "exact rank" sub-bet (see
    `app.services.betting_service`'s sub_bet handling for `TEAM_BREAK`).

    Reuses the EXACT same Monte Carlo mechanics `_simulate_probability` uses for "does it break
    at all" (same seeded RNG per team, same `_draw_round_points` history-weighted draw) --
    deliberately not the Plackett-Luce/softmax "power rating" model the rest of this app's odds
    engine (`app.domain.odds`) uses for round_winner/champion/etc. Those are a genuinely
    different pricing subsystem here: break probability is driven by each team's own points
    history and how many rounds remain, which a static power rating doesn't model, and there's
    already a working simulator for exactly that -- reading a different summary statistic
    (final rank instead of "in the top break_size") off the same simulated standings keeps this
    consistent with `team_break_probability` instead of introducing a second, incompatible way
    to price the same underlying event.
    """
    rng = random.Random(f"break-predictor:{team_id}")
    rank_counts: dict[int, int] = defaultdict(int)
    for _ in range(num_simulations):
        final_points = dict(points_by_team)
        for tid in final_points:
            history = placement_history.get(tid, {})
            for _round in range(rounds_remaining):
                final_points[tid] += _draw_round_points(history, rng)
        ranked = sorted(final_points.items(), key=lambda kv: (-kv[1], kv[0]))
        rank_of_team = next(i + 1 for i, (tid, _points) in enumerate(ranked) if tid == team_id)
        rank_counts[rank_of_team] += 1
    return {rank: count / num_simulations for rank, count in rank_counts.items()}
