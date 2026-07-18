"""Scoring rules for each bet type -- pure functions over plain payload/outcome dicts.

Every prediction is a market-specific JSON ``payload`` (what the user guessed) scored against
an ``outcome`` dict (what actually happened, assembled by the settlement service from the
tournament's scraped data) using a ``points_rule`` dict (admin-tunable payout amounts, with
sane defaults so an admin creating a market doesn't have to specify every knob).

The unit throughout this module -- ``points_rule["points"]``, ``per_hit``,
``exact_position_bonus``, and the float every scoring function returns -- is **fictional USD**
("dólares apostados"), not an abstract point count: there is no real money anywhere in this
platform, but the friend group's running score is expressed and displayed as dollars won/lost
rather than points, per the product's framing. The math is identical either way; only the
label the frontend puts next to the number changes (e.g. "$100" instead of "100 pts").

Adding a new bet type means adding one function here and registering it in ``_STRATEGIES`` --
the settlement service itself never needs to change, since it only ever calls
``score_prediction(bet_type, ...)``.

A malformed/incomplete payload (e.g. a client bug, or a market whose shape changed) scores 0
rather than raising -- a single bad prediction must never abort settlement for everyone else.
"""

from collections.abc import Callable

from app.models.enums import BetType


def _champion(payload: dict, outcome: dict, points_rule: dict) -> float:
    if payload.get("team_id") is None or outcome.get("champion_team_id") is None:
        return 0.0
    if payload["team_id"] == outcome["champion_team_id"]:
        return float(points_rule.get("points", 100))
    return 0.0


def _top_n(
    payload: dict, outcome: dict, points_rule: dict, *, id_key: str, outcome_key: str
) -> float:
    predicted: list = payload.get(id_key) or []
    actual: list = outcome.get(outcome_key) or []
    if not predicted or not actual:
        return 0.0
    per_hit = float(points_rule.get("per_hit", 10))
    exact_bonus = float(points_rule.get("exact_position_bonus", 5))
    actual_position = {item_id: i for i, item_id in enumerate(actual)}

    total = 0.0
    for i, item_id in enumerate(predicted):
        if item_id not in actual_position:
            continue
        total += per_hit
        if actual_position[item_id] == i:
            total += exact_bonus
    return total


def _top_n_break(payload: dict, outcome: dict, points_rule: dict) -> float:
    return _top_n(payload, outcome, points_rule, id_key="team_ids", outcome_key="breaking_team_ids")


def _top_n_speakers(payload: dict, outcome: dict, points_rule: dict) -> float:
    return _top_n(
        payload, outcome, points_rule, id_key="speaker_ids", outcome_key="top_speaker_ids"
    )


def _round_winner(payload: dict, outcome: dict, points_rule: dict) -> float:
    if payload.get("debate_id") is None or payload.get("team_id") is None:
        return 0.0
    if outcome.get("debate_id") != payload["debate_id"]:
        return 0.0
    if payload["team_id"] == outcome.get("winning_team_id"):
        return float(points_rule.get("points", 20))
    return 0.0


def _head_to_head(payload: dict, outcome: dict, points_rule: dict) -> float:
    predicted_winner = payload.get("predicted_winner_id")
    if predicted_winner is None:
        return 0.0
    if predicted_winner == outcome.get("higher_ranked_team_id"):
        return float(points_rule.get("points", 15))
    return 0.0


def _breakout_team(payload: dict, outcome: dict, points_rule: dict) -> float:
    if payload.get("team_id") is None or outcome.get("breakout_team_id") is None:
        return 0.0
    if payload["team_id"] == outcome["breakout_team_id"]:
        return float(points_rule.get("points", 30))
    return 0.0


def _best_institution(payload: dict, outcome: dict, points_rule: dict) -> float:
    predicted = payload.get("institution_code")
    actual = outcome.get("institution_code")
    if not predicted or not actual:
        return 0.0
    if predicted.strip().casefold() == actual.strip().casefold():
        return float(points_rule.get("points", 20))
    return 0.0


_STRATEGIES: dict[BetType, Callable[[dict, dict, dict], float]] = {
    BetType.CHAMPION: _champion,
    BetType.TOP_N_BREAK: _top_n_break,
    BetType.TOP_N_SPEAKERS: _top_n_speakers,
    BetType.ROUND_WINNER: _round_winner,
    BetType.HEAD_TO_HEAD: _head_to_head,
    BetType.BREAKOUT_TEAM: _breakout_team,
    BetType.BEST_INSTITUTION: _best_institution,
}


def score_prediction(bet_type: BetType, payload: dict, outcome: dict, points_rule: dict) -> float:
    strategy = _STRATEGIES.get(bet_type)
    if strategy is None:
        raise ValueError(f"no scoring strategy registered for bet type {bet_type!r}")
    return strategy(payload, outcome, points_rule or {})
