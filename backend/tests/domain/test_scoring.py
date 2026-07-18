import pytest

from app.domain.scoring import score_prediction
from app.models.enums import BetType


def test_champion_exact_match_scores_default_points() -> None:
    assert score_prediction(BetType.CHAMPION, {"team_id": 1}, {"champion_team_id": 1}, {}) == 100.0


def test_champion_miss_scores_zero() -> None:
    assert score_prediction(BetType.CHAMPION, {"team_id": 1}, {"champion_team_id": 2}, {}) == 0.0


def test_champion_respects_custom_points_rule() -> None:
    result = score_prediction(
        BetType.CHAMPION, {"team_id": 1}, {"champion_team_id": 1}, {"points": 50}
    )
    assert result == 50.0


def test_champion_malformed_payload_scores_zero_not_crash() -> None:
    assert score_prediction(BetType.CHAMPION, {}, {"champion_team_id": 1}, {}) == 0.0
    assert score_prediction(BetType.CHAMPION, {"team_id": 1}, {}, {}) == 0.0


def test_top_n_break_awards_per_hit_and_exact_position_bonus() -> None:
    payload = {"team_ids": [1, 2, 3]}
    outcome = {"breaking_team_ids": [1, 5, 3, 2]}
    result = score_prediction(BetType.TOP_N_BREAK, payload, outcome, {})
    # team 1: index 0 in both -> hit (10) + exact position bonus (5) = 15
    # team 2: predicted index 1, actually at index 3 -> hit only = 10
    # team 3: index 2 in both -> hit (10) + exact position bonus (5) = 15
    assert result == 15.0 + 10.0 + 15.0


def test_top_n_break_ignores_predictions_not_in_outcome() -> None:
    payload = {"team_ids": [99]}
    outcome = {"breaking_team_ids": [1, 2, 3]}
    assert score_prediction(BetType.TOP_N_BREAK, payload, outcome, {}) == 0.0


def test_top_n_speakers_uses_custom_points_rule() -> None:
    payload = {"speaker_ids": [7]}
    outcome = {"top_speaker_ids": [7]}
    result = score_prediction(
        BetType.TOP_N_SPEAKERS, payload, outcome, {"per_hit": 8, "exact_position_bonus": 2}
    )
    assert result == 10.0


def test_round_winner_requires_matching_debate_and_team() -> None:
    payload = {"debate_id": 5, "team_id": 1}
    assert (
        score_prediction(BetType.ROUND_WINNER, payload, {"debate_id": 5, "winning_team_id": 1}, {})
        == 20.0
    )
    assert (
        score_prediction(BetType.ROUND_WINNER, payload, {"debate_id": 5, "winning_team_id": 2}, {})
        == 0.0
    )
    assert (
        score_prediction(BetType.ROUND_WINNER, payload, {"debate_id": 9, "winning_team_id": 1}, {})
        == 0.0
    )


def test_head_to_head_scores_binary() -> None:
    payload = {"team_a_id": 1, "team_b_id": 2, "predicted_winner_id": 1}
    assert score_prediction(BetType.HEAD_TO_HEAD, payload, {"higher_ranked_team_id": 1}, {}) == 15.0
    assert score_prediction(BetType.HEAD_TO_HEAD, payload, {"higher_ranked_team_id": 2}, {}) == 0.0


def test_breakout_team_scores_binary() -> None:
    assert (
        score_prediction(BetType.BREAKOUT_TEAM, {"team_id": 3}, {"breakout_team_id": 3}, {}) == 30.0
    )
    assert (
        score_prediction(BetType.BREAKOUT_TEAM, {"team_id": 3}, {"breakout_team_id": 4}, {}) == 0.0
    )


def test_best_institution_is_case_insensitive() -> None:
    payload = {"institution_code": "pucp"}
    assert (
        score_prediction(BetType.BEST_INSTITUTION, payload, {"institution_code": "PUCP"}, {})
        == 20.0
    )


def test_score_prediction_raises_for_unregistered_bet_type() -> None:
    class FakeBetType:
        pass

    with pytest.raises(ValueError):
        score_prediction(FakeBetType(), {}, {}, {})  # type: ignore[arg-type]
