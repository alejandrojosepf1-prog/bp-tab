import math

import pytest

from app.domain.odds import (
    HOUSE_MARGIN,
    MAX_ODDS,
    MIN_ODDS,
    decimal_odds_from_probability,
    ordered_sequence_odds,
    single_candidate_odds,
    softmax_probabilities,
)


def test_softmax_probabilities_sum_to_one() -> None:
    probs = softmax_probabilities({"a": 10.0, "b": 5.0, "c": 1.0})
    assert math.isclose(sum(probs.values()), 1.0, rel_tol=1e-9)


def test_softmax_probabilities_favors_higher_power() -> None:
    probs = softmax_probabilities({"favorite": 20.0, "underdog": 5.0})
    assert probs["favorite"] > probs["underdog"]


def test_softmax_probabilities_equal_power_is_uniform() -> None:
    probs = softmax_probabilities({"a": 7.0, "b": 7.0, "c": 7.0})
    assert math.isclose(probs["a"], probs["b"])
    assert math.isclose(probs["b"], probs["c"])
    assert math.isclose(sum(probs.values()), 1.0)


def test_softmax_probabilities_empty_input() -> None:
    assert softmax_probabilities({}) == {}


def test_softmax_probabilities_rejects_nonpositive_temperature() -> None:
    with pytest.raises(ValueError):
        softmax_probabilities({"a": 1.0}, temperature=0)


def test_decimal_odds_applies_house_margin() -> None:
    # The fair 1/p price is shaved by the house margin so the book holds an edge:
    # 1/0.5 = 2.0 -> 2.0 / 1.07 = 1.87; 1/0.4 = 2.5 -> 2.5 / 1.07 = 2.34.
    assert decimal_odds_from_probability(0.5) == round(2.0 / (1.0 + HOUSE_MARGIN), 2)
    assert decimal_odds_from_probability(0.4) == round(2.5 / (1.0 + HOUSE_MARGIN), 2)


def test_decimal_odds_clamped_to_realistic_band() -> None:
    # A near-certainty is floored to MIN_ODDS (still pays a little, never ~1.00), and any
    # vanishingly small probability is capped at MAX_ODDS instead of blowing up to ~10000x.
    assert decimal_odds_from_probability(1.0) == MIN_ODDS
    assert decimal_odds_from_probability(0.0) == MAX_ODDS
    assert decimal_odds_from_probability(0.0) == decimal_odds_from_probability(0.0001)


def test_decimal_odds_never_below_a_fair_book() -> None:
    # For any mid-range probability the offered odds must be strictly below the fair 1/p price
    # (that gap IS the house edge).
    for p in (0.2, 0.35, 0.5, 0.7):
        assert decimal_odds_from_probability(p) < 1.0 / p


def test_single_candidate_odds_favorite_pays_less_than_underdog() -> None:
    power = {"favorite": 9.0, "underdog": 5.0, "longshot": 1.0}
    favorite_odds = single_candidate_odds(power, "favorite")
    underdog_odds = single_candidate_odds(power, "underdog")
    longshot_odds = single_candidate_odds(power, "longshot")
    assert favorite_odds < underdog_odds < longshot_odds
    assert favorite_odds > 1.0  # never literally break-even/free money


def test_single_candidate_odds_two_equal_candidates_reflects_margin() -> None:
    # Two equal candidates are a fair coin toss (2.0 each); after the house margin, ~1.87.
    odds = single_candidate_odds({"a": 10.0, "b": 10.0}, "a")
    assert math.isclose(odds, round(2.0 / (1.0 + HOUSE_MARGIN), 2), rel_tol=0.01)


def test_single_candidate_odds_unknown_candidate_raises() -> None:
    with pytest.raises(KeyError):
        single_candidate_odds({"a": 1.0}, "not-in-field")


def test_ordered_sequence_odds_higher_than_any_single_leg() -> None:
    power = {"a": 10.0, "b": 8.0, "c": 6.0, "d": 4.0, "e": 2.0}
    combined = ordered_sequence_odds(power, ["a", "b", "c"])
    leg_one = single_candidate_odds(power, "a")
    # A 3-leg parlay must pay strictly more than picking just the first leg correctly.
    assert combined > leg_one


def test_ordered_sequence_odds_matches_manual_plackett_luce_calc() -> None:
    power = {"a": 10.0, "b": 10.0, "c": 10.0}
    # All equal power -> P(a first) = 1/3, P(b second | a picked) = 1/2, P(c third) = 1 -> 1/6,
    # i.e. fair odds of 6.0, shaved by the house margin to 6.0 / 1.07 ~= 5.61.
    combined = ordered_sequence_odds(power, ["a", "b", "c"])
    assert math.isclose(combined, round(6.0 / (1.0 + HOUSE_MARGIN), 2), rel_tol=0.01)


def test_ordered_sequence_odds_rejects_empty_sequence() -> None:
    with pytest.raises(ValueError):
        ordered_sequence_odds({"a": 1.0}, [])


def test_ordered_sequence_odds_rejects_duplicate_picks() -> None:
    with pytest.raises(ValueError):
        ordered_sequence_odds({"a": 1.0, "b": 1.0}, ["a", "a"])


def test_ordered_sequence_odds_unknown_candidate_raises() -> None:
    with pytest.raises(KeyError):
        ordered_sequence_odds({"a": 1.0, "b": 1.0}, ["a", "ghost"])
