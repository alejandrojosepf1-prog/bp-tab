import pytest

from app.domain.bet_outcomes import did_prediction_win
from app.models.enums import BetType


def test_champion_win() -> None:
    assert did_prediction_win(BetType.CHAMPION, {"team_id": 1}, {"champion_team_id": 1}) is True


def test_champion_loss() -> None:
    assert did_prediction_win(BetType.CHAMPION, {"team_id": 1}, {"champion_team_id": 2}) is False


def test_champion_missing_payload() -> None:
    assert did_prediction_win(BetType.CHAMPION, {}, {"champion_team_id": 1}) is False


def test_top_n_break_exact_match_wins() -> None:
    payload = {"team_ids": [1, 2, 3]}
    outcome = {"breaking_team_ids": [1, 2, 3, 4, 5]}
    assert did_prediction_win(BetType.TOP_N_BREAK, payload, outcome) is True


def test_top_n_break_partial_match_is_a_loss() -> None:
    """All-or-nothing parlay: 2 of 3 right still loses."""
    payload = {"team_ids": [1, 2, 3]}
    outcome = {"breaking_team_ids": [1, 2, 9, 4, 5]}
    assert did_prediction_win(BetType.TOP_N_BREAK, payload, outcome) is False


def test_top_n_break_wrong_order_is_a_loss() -> None:
    payload = {"team_ids": [2, 1, 3]}
    outcome = {"breaking_team_ids": [1, 2, 3]}
    assert did_prediction_win(BetType.TOP_N_BREAK, payload, outcome) is False


def test_top_n_speakers_exact_match_wins() -> None:
    payload = {"speaker_ids": [10, 20]}
    outcome = {"top_speaker_ids": [10, 20, 30]}
    assert did_prediction_win(BetType.TOP_N_SPEAKERS, payload, outcome) is True


def test_round_winner_win() -> None:
    payload = {"debate_id": 5, "team_id": 1}
    outcome = {"debate_id": 5, "winning_team_id": 1}
    assert did_prediction_win(BetType.ROUND_WINNER, payload, outcome) is True


def test_round_winner_wrong_debate_is_a_loss() -> None:
    payload = {"debate_id": 5, "team_id": 1}
    outcome = {"debate_id": 6, "winning_team_id": 1}
    assert did_prediction_win(BetType.ROUND_WINNER, payload, outcome) is False


def test_head_to_head_win() -> None:
    payload = {"predicted_winner_id": 1}
    outcome = {"higher_ranked_team_id": 1}
    assert did_prediction_win(BetType.HEAD_TO_HEAD, payload, outcome) is True


def test_breakout_team_win() -> None:
    payload = {"team_id": 1}
    outcome = {"breakout_team_id": 1}
    assert did_prediction_win(BetType.BREAKOUT_TEAM, payload, outcome) is True


def test_best_institution_case_insensitive_win() -> None:
    payload = {"institution_code": "pucp"}
    outcome = {"institution_code": "PUCP"}
    assert did_prediction_win(BetType.BEST_INSTITUTION, payload, outcome) is True


def test_best_institution_loss() -> None:
    payload = {"institution_code": "PUCP"}
    outcome = {"institution_code": "OTHER"}
    assert did_prediction_win(BetType.BEST_INSTITUTION, payload, outcome) is False


def test_unknown_bet_type_raises() -> None:
    with pytest.raises(ValueError):
        did_prediction_win("not-a-real-bet-type", {}, {})  # type: ignore[arg-type]
