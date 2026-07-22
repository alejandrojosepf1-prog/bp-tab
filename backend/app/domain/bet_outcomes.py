"""Did a Prediction win, per bet_type -- pure boolean functions over plain payload/outcome
dicts, exactly like the fixed-points `domain.scoring` module this replaces used to score them.

The betting model is now fixed-odds (see `domain.odds`): a prediction's payout is
`stake_amount * odds` if it won, `0.0` if it didn't -- there is no more partial credit for a
top-N pick that gets some but not all legs right, matching a real parlay ("all legs correct or
the ticket pays nothing"). `outcome` is assembled by `services.betting_service` from the
tournament's scraped data exactly as before; only the win/lose determination changed.

A malformed/incomplete payload (e.g. a client bug, or a market whose shape changed) is scored as
a loss rather than raising -- a single bad prediction must never abort settlement for everyone
else.
"""

from collections.abc import Callable

from app.models.enums import BetType


def _champion(payload: dict, outcome: dict) -> bool:
    return (
        payload.get("team_id") is not None
        and payload["team_id"] == outcome.get("champion_team_id")
    )


def _ordered_top_n(payload: dict, outcome: dict, *, id_key: str, outcome_key: str) -> bool:
    predicted: list = payload.get(id_key) or []
    actual: list = outcome.get(outcome_key) or []
    if not predicted or not actual:
        return False
    return list(predicted) == list(actual)[: len(predicted)]


def _top_n_break(payload: dict, outcome: dict) -> bool:
    return _ordered_top_n(payload, outcome, id_key="team_ids", outcome_key="breaking_team_ids")


def _top_n_speakers(payload: dict, outcome: dict) -> bool:
    return _ordered_top_n(
        payload, outcome, id_key="speaker_ids", outcome_key="top_speaker_ids"
    )


def _round_winner(payload: dict, outcome: dict) -> bool:
    if payload.get("debate_id") is None or payload.get("team_id") is None:
        return False
    return (
        outcome.get("debate_id") == payload["debate_id"]
        and payload["team_id"] == outcome.get("winning_team_id")
    )


def _head_to_head(payload: dict, outcome: dict) -> bool:
    predicted_winner = payload.get("predicted_winner_id")
    return predicted_winner is not None and predicted_winner == outcome.get(
        "higher_ranked_team_id"
    )


def _breakout_team(payload: dict, outcome: dict) -> bool:
    return (
        payload.get("team_id") is not None
        and payload["team_id"] == outcome.get("breakout_team_id")
    )


def _best_institution(payload: dict, outcome: dict) -> bool:
    predicted = payload.get("institution_code")
    actual = outcome.get("institution_code")
    if not predicted or not actual:
        return False
    return predicted.strip().casefold() == actual.strip().casefold()


def _round_full_call(payload: dict, outcome: dict) -> bool:
    if payload.get("debate_id") is None or not payload.get("team_ids"):
        return False
    return (
        outcome.get("debate_id") == payload["debate_id"]
        and list(payload["team_ids"]) == outcome.get("actual_order")
    )


def _top_speaker_position(payload: dict, outcome: dict) -> bool:
    speaker_id = payload.get("speaker_id")
    position = payload.get("position")
    if speaker_id is None or position is None:
        return False
    return outcome.get("position_winners", {}).get(position) == speaker_id


def _team_break(payload: dict, outcome: dict) -> bool:
    team_id = payload.get("team_id")
    if team_id is None:
        return False
    return team_id in (outcome.get("breaking_team_ids") or [])


_STRATEGIES: dict[BetType, Callable[[dict, dict], bool]] = {
    BetType.CHAMPION: _champion,
    BetType.TOP_N_BREAK: _top_n_break,
    BetType.TOP_N_SPEAKERS: _top_n_speakers,
    BetType.ROUND_WINNER: _round_winner,
    BetType.HEAD_TO_HEAD: _head_to_head,
    BetType.BREAKOUT_TEAM: _breakout_team,
    BetType.BEST_INSTITUTION: _best_institution,
    BetType.ROUND_FULL_CALL: _round_full_call,
    BetType.TOP_SPEAKER_POSITION: _top_speaker_position,
    BetType.TEAM_BREAK: _team_break,
}


def did_prediction_win(bet_type: BetType, payload: dict, outcome: dict) -> bool:
    strategy = _STRATEGIES.get(bet_type)
    if strategy is None:
        raise ValueError(f"no outcome strategy registered for bet type {bet_type!r}")
    return strategy(payload, outcome)
