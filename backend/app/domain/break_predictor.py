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
    with a simulated probability for the teams still genuinely in contention.

    Runs ONE shared Monte Carlo simulation of the whole field (`_simulate_field`) rather than
    a separate simulation per "alive" team. Besides being O(num_teams x num_simulations) instead
    of O(num_teams^2 x num_simulations) -- the difference between this staying fast for a
    realistic field and it hanging the request for tens of seconds -- a shared simulation is
    also what makes probabilities across teams consistent with each other: every trial breaks
    exactly `break_size` teams out of the SAME simulated world, so the probabilities this
    returns necessarily sum to ~break_size across the field. Simulating each team against its
    own independent random draws (the previous approach) gave every team an uncorrelated
    Monte Carlo estimate with its own sampling noise, so nothing guaranteed that -- which is
    exactly why two teams with near-identical real chances could end up priced very
    differently."""
    points_by_team = {s.team_id: s.team_points for s in standings}
    placement_history = placement_history_by_team(standings)

    statuses: dict[int, str] = {}
    points_needed: dict[int, int | None] = {}
    any_alive = False
    for team in standings:
        others_points = [p for tid, p in points_by_team.items() if tid != team.team_id]
        status = classify_status(
            team.team_points,
            other_teams_points=others_points,
            rounds_remaining=rounds_remaining,
            break_size=break_size,
        )
        statuses[team.team_id] = status
        any_alive = any_alive or status == "alive"
        points_needed[team.team_id] = (
            points_needed_for_safety(
                team.team_points,
                other_teams_points=others_points,
                rounds_remaining=rounds_remaining,
                break_size=break_size,
            )
            if status != "safe"
            else None
        )

    rank_counts = (
        _simulate_field(
            points_by_team,
            placement_history,
            rounds_remaining,
            num_simulations,
            random.Random("break-predictor:field"),
        )
        if any_alive
        else {}
    )

    assessments = []
    for team in standings:
        status = statuses[team.team_id]
        if status == "safe":
            probability = 1.0
        elif status == "eliminated":
            probability = 0.0
        else:
            counts = rank_counts.get(team.team_id, {})
            probability = sum(c for r, c in counts.items() if r <= break_size) / num_simulations
        assessments.append(
            BreakAssessment(
                team_id=team.team_id,
                status=status,
                probability=probability,
                projected_rank=team.rank,
                points_needed_for_safety=points_needed[team.team_id],
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


def _simulate_field(
    points_by_team: dict[int, int],
    placement_history: dict[int, dict[int, int]],
    rounds_remaining: int,
    num_simulations: int,
    rng: random.Random,
) -> dict[int, dict[int, int]]:
    """Runs `num_simulations` trials of the WHOLE field at once -- each trial draws every team's
    remaining rounds from its own placement history, then ranks the full field once, so the
    same trial answers "who breaks" for every team simultaneously and consistently (the same
    fixed number of teams breaks in every single trial, same as a real break). Returns, per
    team_id, a {final_rank: times_landed_there} counter across all trials --
    both break probability (sum of counts for ranks <= break_size) and the exact-rank
    distribution are read off these same counts, so both stay consistent with each other too."""
    team_ids = list(points_by_team)
    rank_counts: dict[int, dict[int, int]] = {tid: defaultdict(int) for tid in team_ids}
    for _ in range(num_simulations):
        final_points = dict(points_by_team)
        for tid in team_ids:
            history = placement_history.get(tid, {})
            for _round in range(rounds_remaining):
                final_points[tid] += _draw_round_points(history, rng)
        ranked = sorted(final_points.items(), key=lambda kv: (-kv[1], kv[0]))
        for rank, (tid, _points) in enumerate(ranked, start=1):
            rank_counts[tid][rank] += 1
    return rank_counts


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

    Reuses `_simulate_field`, the same whole-field Monte Carlo `build_break_report` uses for
    "does it break at all" -- deliberately not the Plackett-Luce/softmax "power rating" model
    the rest of this app's odds engine (`app.domain.odds`) uses for round_winner/champion/etc.
    Those are a genuinely different pricing subsystem here: break probability is driven by each
    team's own points history and how many rounds remain, which a static power rating doesn't
    model, and there's already a working simulator for exactly that -- reading a different
    summary statistic (final rank instead of "in the top break_size") off the same simulated
    standings keeps this consistent with `team_break_probability` instead of introducing a
    second, incompatible way to price the same underlying event.
    """
    rng = random.Random(f"break-predictor:{team_id}")
    rank_counts = _simulate_field(
        points_by_team, placement_history, rounds_remaining, num_simulations, rng
    )
    counts = rank_counts.get(team_id, {})
    return {rank: count / num_simulations for rank, count in counts.items()}
