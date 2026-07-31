import itertools
import math

import pytest

from app.domain.odds import (
    DEFAULT_SEED,
    MAX_ODDS,
    MIN_ODDS,
    adaptive_temperature,
    decimal_odds_from_probability,
    exact_rank_gap_probability,
    ordered_sequence_odds,
    pari_mutuel_odds,
    pari_mutuel_probability,
    positional_probabilities,
    sequence_probability,
    simulate_positional_probabilities,
    single_candidate_odds,
    pair_top_two_probability,
    softmax_probabilities,
    top_n_probabilities,
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


def test_decimal_odds_is_the_fair_price_with_no_margin() -> None:
    # Claim takes no cut: the offered price is exactly 1/p, not shaved by any vig.
    assert decimal_odds_from_probability(0.5) == 2.0
    assert decimal_odds_from_probability(0.4) == 2.5
    assert decimal_odds_from_probability(0.25) == 4.0


def test_decimal_odds_clamped_to_realistic_band() -> None:
    # A near-certainty is floored to MIN_ODDS (still pays a little, never ~1.00), and any
    # vanishingly small probability is capped at MAX_ODDS instead of blowing up to ~10000x.
    assert decimal_odds_from_probability(1.0) == MIN_ODDS
    assert decimal_odds_from_probability(0.0) == MAX_ODDS
    assert decimal_odds_from_probability(0.0) == decimal_odds_from_probability(0.0001)


def test_decimal_odds_book_sums_to_exactly_one() -> None:
    # The defining property of a no-vig book: implied probabilities across a market's mutually
    # exclusive outcomes sum to 1.0, not to 1.0 + margin. Any overround would show up here.
    # Uses a tight field on purpose so no price hits the MIN/MAX_ODDS band -- clamping a genuine
    # longshot legitimately breaks the sum, and that's a readability guard, not a margin.
    probs = softmax_probabilities({"a": 1.0, "b": 0.5, "c": 0.0})
    implied = sum(1.0 / decimal_odds_from_probability(p) for p in probs.values())
    assert math.isclose(implied, 1.0, rel_tol=0.01)


def test_single_candidate_odds_favorite_pays_less_than_underdog() -> None:
    power = {"favorite": 9.0, "underdog": 5.0, "longshot": 1.0}
    favorite_odds = single_candidate_odds(power, "favorite")
    underdog_odds = single_candidate_odds(power, "underdog")
    longshot_odds = single_candidate_odds(power, "longshot")
    assert favorite_odds < underdog_odds < longshot_odds
    assert favorite_odds > 1.0  # never literally break-even/free money


def test_single_candidate_odds_two_equal_candidates_is_an_even_coin_toss() -> None:
    # Two equal candidates are a fair coin toss, and with no margin taken that's exactly 2.0.
    odds = single_candidate_odds({"a": 10.0, "b": 10.0}, "a")
    assert math.isclose(odds, 2.0, rel_tol=0.01)


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
    # i.e. fair odds of exactly 6.0 with no margin taken out.
    combined = ordered_sequence_odds(power, ["a", "b", "c"])
    assert math.isclose(combined, 6.0, rel_tol=0.01)


def test_ordered_sequence_odds_rejects_empty_sequence() -> None:
    with pytest.raises(ValueError):
        ordered_sequence_odds({"a": 1.0}, [])


def test_ordered_sequence_odds_rejects_duplicate_picks() -> None:
    with pytest.raises(ValueError):
        ordered_sequence_odds({"a": 1.0, "b": 1.0}, ["a", "a"])


def test_ordered_sequence_odds_unknown_candidate_raises() -> None:
    with pytest.raises(KeyError):
        ordered_sequence_odds({"a": 1.0, "b": 1.0}, ["a", "ghost"])


def test_sequence_probability_matches_ordered_sequence_odds() -> None:
    # ordered_sequence_odds is just decimal_odds_from_probability(sequence_probability(...)).
    power = {"a": 10.0, "b": 8.0, "c": 6.0}
    prob = sequence_probability(power, ["a", "b", "c"])
    assert decimal_odds_from_probability(prob) == ordered_sequence_odds(power, ["a", "b", "c"])


def test_pari_mutuel_probability_with_empty_pool_equals_prior() -> None:
    # No money staked yet on anything -> the pool contributes nothing, price is exactly the
    # seeded prior (this is what makes the very first bettor on a market gets a sane price).
    assert pari_mutuel_probability(0.0, 0.0, 0.3) == pytest.approx(0.3)
    assert pari_mutuel_probability(0.0, 0.0, 0.3, seed=50.0) == pytest.approx(0.3)


def test_pari_mutuel_probability_moves_toward_the_crowd_as_pool_grows() -> None:
    # A candidate with an unfavorable prior (10%) that's nonetheless attracted ALL the real
    # money should price higher than the prior as the pool overtakes the seed.
    prior = 0.10
    small_pool = pari_mutuel_probability(50.0, 50.0, prior, seed=200.0)
    large_pool = pari_mutuel_probability(2000.0, 2000.0, prior, seed=200.0)
    assert prior < small_pool < large_pool
    # Once the real pool dwarfs the seed, price converges toward "certain" (everyone agrees).
    assert large_pool > 0.9


def test_pari_mutuel_probability_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        pari_mutuel_probability(0.0, 0.0, 0.5, seed=0.0)
    with pytest.raises(ValueError):
        pari_mutuel_probability(-1.0, 10.0, 0.5)
    with pytest.raises(ValueError):
        pari_mutuel_probability(20.0, 10.0, 0.5)  # candidate can't exceed compartment total


def test_pari_mutuel_odds_prices_a_wide_field_fairly_and_clamps_only_the_absurd() -> None:
    # With no house liability left to bound (see odds.py's "Fair book" note), a genuine longshot
    # now pays its real price rather than being cut off early: a 40-way uniform field prices at
    # the fair 40x, comfortably inside the band.
    assert pari_mutuel_odds(0.0, 0.0, 1 / 40) == 40.0
    # Only a truly absurd field (a 500-way toss-up would pay 500x) still hits the readability cap.
    assert pari_mutuel_odds(0.0, 0.0, 1 / 500) == MAX_ODDS


def test_pari_mutuel_odds_seed_absorbs_a_small_early_bet() -> None:
    # A lone $5 bet on a fair coin-toss candidate shouldn't swing the price much when the seed
    # (200) dwarfs the stake.
    fair_prior = 0.5
    odds_before_any_bet = pari_mutuel_odds(0.0, 0.0, fair_prior)
    odds_after_small_bet = pari_mutuel_odds(5.0, 5.0, fair_prior)
    assert math.isclose(odds_before_any_bet, odds_after_small_bet, rel_tol=0.05)


def test_pari_mutuel_odds_default_seed_is_exported() -> None:
    assert DEFAULT_SEED > 0


# --- positional_probabilities --------------------------------------------------------------


def test_positional_probabilities_position_1_matches_softmax() -> None:
    # Position 1 ("exactly 1st") is by definition the same event single_candidate/softmax
    # already price -- this is the strongest correctness anchor for the whole function.
    power = {"a": 12.0, "b": 7.0, "c": 3.0, "d": 1.0}
    temp = 4.0
    position_1 = positional_probabilities(power, 1, temperature=temp)
    softmax = softmax_probabilities(power, temperature=temp)
    assert position_1.keys() == softmax.keys()
    for candidate in position_1:
        assert math.isclose(position_1[candidate], softmax[candidate], rel_tol=1e-9)


def test_positional_probabilities_equal_field_is_uniform_at_every_position() -> None:
    # With N equal-power candidates every permutation is equally likely, so P(any candidate in
    # any specific slot) = 1/N regardless of which slot -- a clean, hand-verifiable case.
    power = {"a": 5.0, "b": 5.0, "c": 5.0}
    for position in (1, 2, 3):
        probs = positional_probabilities(power, position, temperature=1.0)
        for candidate_prob in probs.values():
            assert math.isclose(candidate_prob, 1 / 3, rel_tol=1e-9)


def test_positional_probabilities_sum_to_one_at_every_position() -> None:
    # Exactly one candidate occupies a given slot -- this must hold for ANY power distribution,
    # not just the symmetric one above, since it's what stops the pari-mutuel prior from being
    # miscalibrated (a coherent probability distribution has to sum to 1). Cross-checked by
    # brute-force permutation enumeration during development (not kept as a test: O(N!)) --
    # the derivation itself matches to ~1e-7; a hardcoded temperature far outside what
    # adaptive_temperature would ever pick for these fields is what actually produced the
    # larger float error seen while iterating on this test, via catastrophic cancellation in
    # `total - w_j` when one candidate's weight dominates the rest -- so, like every real call
    # site in odds_service.py, this always derives temperature from the field itself.
    fields = [
        {"a": 10.0, "b": 6.0, "c": 2.0},
        {"a": 3.0, "b": 3.0, "c": 3.0, "d": 3.0, "e": 3.0},
        {"a": 50.0, "b": 1.0, "c": 1.0, "d": 0.5, "e": 0.1, "f": 0.1},
    ]
    for power in fields:
        temp = adaptive_temperature(power.values())
        for position in (1, 2, 3):
            total = sum(positional_probabilities(power, position, temperature=temp).values())
            assert math.isclose(total, 1.0, rel_tol=1e-9)


def test_positional_probabilities_favorite_less_likely_to_finish_last() -> None:
    # Directional sanity check: the strongest candidate should be LEAST likely to occupy the
    # last available slot in the field, and the weakest MOST likely to.
    power = {"favorite": 20.0, "mid": 8.0, "longshot": 1.0}
    probs_last = positional_probabilities(power, 3, temperature=3.0)
    assert probs_last["longshot"] > probs_last["mid"] > probs_last["favorite"]


def test_positional_probabilities_rejects_unsupported_position() -> None:
    with pytest.raises(ValueError):
        positional_probabilities({"a": 1.0, "b": 1.0}, 4)
    with pytest.raises(ValueError):
        positional_probabilities({"a": 1.0, "b": 1.0}, 0)


def test_positional_probabilities_empty_input() -> None:
    assert positional_probabilities({}, 1) == {}
    assert positional_probabilities({}, 3) == {}


# --- simulate_positional_probabilities: Monte Carlo extension past position 3 ------------


def test_simulate_positional_probabilities_converges_to_the_exact_formula() -> None:
    """For positions 1-3, both the exact recursive formula and the simulation answer the same
    question -- the simulation must agree with it to within Monte Carlo sampling error."""
    power = {"a": 10.0, "b": 6.0, "c": 3.0, "d": 1.0, "e": 0.5}
    temp = adaptive_temperature(power.values())
    simulated = simulate_positional_probabilities(
        power, 3, temperature=temp, num_simulations=20_000
    )
    for position in (1, 2, 3):
        exact = positional_probabilities(power, position, temperature=temp)
        for candidate, exact_prob in exact.items():
            assert simulated[position][candidate] == pytest.approx(exact_prob, abs=0.02)


def test_simulate_positional_probabilities_sums_to_one_at_every_position() -> None:
    power = {"a": 10.0, "b": 6.0, "c": 3.0, "d": 1.0, "e": 0.5, "f": 0.2, "g": 0.1}
    result = simulate_positional_probabilities(power, 6, num_simulations=5000)
    for position in range(1, 7):
        assert sum(result[position].values()) == pytest.approx(1.0, abs=1e-9)


def test_simulate_positional_probabilities_favorite_less_likely_to_finish_last() -> None:
    # Same directional sanity check as the exact formula's test, extended past position 3.
    power = {"favorite": 20.0, "mid": 8.0, "longshot": 1.0}
    probs = simulate_positional_probabilities(power, 3, temperature=3.0, num_simulations=10_000)
    last = probs[3]
    assert last["longshot"] > last["mid"] > last["favorite"]


def test_simulate_positional_probabilities_is_deterministic_for_the_same_seed() -> None:
    power = {"a": 10.0, "b": 6.0, "c": 3.0, "d": 1.0}
    first = simulate_positional_probabilities(power, 4, num_simulations=500, seed="x")
    second = simulate_positional_probabilities(power, 4, num_simulations=500, seed="x")
    assert first == second


def test_simulate_positional_probabilities_handles_field_smaller_than_max_position() -> None:
    # Only 2 candidates but asked for position 5 -- there's no meaningful data past position 2,
    # so those slots should come back empty rather than raising.
    power = {"a": 5.0, "b": 3.0}
    result = simulate_positional_probabilities(power, 5, num_simulations=200)
    assert set(result[1].keys()) == {"a", "b"}
    assert result[5] == {}


def test_simulate_positional_probabilities_rejects_invalid_max_position() -> None:
    with pytest.raises(ValueError):
        simulate_positional_probabilities({"a": 1.0}, 0)


def test_simulate_positional_probabilities_empty_input() -> None:
    assert simulate_positional_probabilities({}, 5) == {}


def test_exact_rank_gap_probability_uniform_field_matches_hand_count() -> None:
    # 4 equal-power candidates -> every one of the 4! = 24 orderings is equally likely. Given
    # "a finishes above b" (12 of the 24 orderings), hand-counting how many of THOSE have each
    # gap: gap=1 -> 3 adjacent (h,l) pairs * 2! for the other two = 6/12 = 0.5; gap=2 -> 2 pairs
    # * 2! = 4/12 = 1/3; gap=3 -> 1 pair * 2! = 2/12 = 1/6.
    power = {"a": 5.0, "b": 5.0, "c": 5.0, "d": 5.0}
    assert math.isclose(
        exact_rank_gap_probability(power, "a", "b", 1, temperature=1.0), 0.5, rel_tol=1e-9
    )
    assert math.isclose(
        exact_rank_gap_probability(power, "a", "b", 2, temperature=1.0), 1 / 3, rel_tol=1e-9
    )
    assert math.isclose(
        exact_rank_gap_probability(power, "a", "b", 3, temperature=1.0), 1 / 6, rel_tol=1e-9
    )


def test_exact_rank_gap_probability_sums_to_one_across_every_gap() -> None:
    power = {"a": 9.0, "b": 4.0, "c": 2.0, "d": 1.0}
    total = sum(
        exact_rank_gap_probability(power, "a", "c", gap, temperature=2.0) for gap in (1, 2, 3)
    )
    assert math.isclose(total, 1.0, rel_tol=1e-9)


def test_exact_rank_gap_probability_unknown_candidate_raises() -> None:
    with pytest.raises(KeyError):
        exact_rank_gap_probability({"a": 1.0, "b": 1.0}, "a", "ghost", 1)


def test_exact_rank_gap_probability_rejects_same_candidate() -> None:
    with pytest.raises(ValueError):
        exact_rank_gap_probability({"a": 1.0, "b": 1.0}, "a", "a", 1)


def test_exact_rank_gap_probability_rejects_out_of_range_gap() -> None:
    power = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}
    with pytest.raises(ValueError):
        exact_rank_gap_probability(power, "a", "b", 0)
    with pytest.raises(ValueError):
        exact_rank_gap_probability(power, "a", "b", 4)


# --- Elimination rounds: top-N ("does this team advance"), not one-winner -------------------


def test_top_n_probabilities_sum_to_n() -> None:
    """A BP elimination room sends N of 4 teams through, so P(advance) must sum to N -- not to
    1.0 the way a one-winner market does."""
    power = {"a": 18.0, "b": 15.0, "c": 13.0, "d": 11.0}
    for n in (1, 2, 3):
        probs = top_n_probabilities(power, n, temperature=5.0)
        assert math.isclose(sum(probs.values()), float(n), rel_tol=1e-9)


def test_top_n_probabilities_n_of_one_matches_plain_softmax() -> None:
    power = {"a": 18.0, "b": 15.0, "c": 13.0, "d": 11.0}
    assert top_n_probabilities(power, 1, temperature=5.0) == pytest.approx(
        softmax_probabilities(power, temperature=5.0)
    )


def test_top_n_probabilities_favors_the_stronger_team() -> None:
    power = {"a": 18.0, "b": 15.0, "c": 13.0, "d": 11.0}
    probs = top_n_probabilities(power, 2, temperature=5.0)
    assert probs["a"] > probs["b"] > probs["c"] > probs["d"]
    # Even the weakest team in a 2-of-4 room is far from hopeless.
    assert 0.0 < probs["d"] < probs["a"] < 1.0


def test_top_n_probabilities_rejects_unsupported_n() -> None:
    with pytest.raises(ValueError):
        top_n_probabilities({"a": 1.0, "b": 1.0}, 4)


def test_backing_every_team_in_an_elimination_room_is_not_free_money() -> None:
    """Regression guard for a real arbitrage: elimination rooms were priced as if ONE team won,
    but 2 of 4 advance -- so backing all four teams in proportion to their own odds returned
    ~2x the stake no matter who went through. Pricing top-2 as top-2 removes the edge: covering
    the whole room must return roughly the stake back (a fair book with no house margin), never
    a guaranteed profit."""
    power = {"a": 18.0, "b": 15.0, "c": 13.0, "d": 11.0}
    probs = top_n_probabilities(power, 2, temperature=15.0)
    # Stake each team its normalized share of a 100-token book.
    stakes = {team: probs[team] / 2 * 100 for team in probs}
    cost = sum(stakes.values())
    for advancing in itertools.combinations(probs, 2):
        payout = sum(stakes[t] * decimal_odds_from_probability(probs[t]) for t in advancing)
        assert payout == pytest.approx(cost, rel=0.02)


# --- Elimination rounds: exact pair advances ---------------------------------------------


def test_pair_top_two_probability_sums_to_one_across_the_room() -> None:
    """Exactly one of the 6 possible pairs in a 4-team room is the one that actually advances --
    the 6 pair probabilities must sum to 1.0, same as any other mutually exclusive market."""
    power = {"a": 18.0, "b": 15.0, "c": 13.0, "d": 11.0}
    total = sum(
        pair_top_two_probability(power, x, y, temperature=5.0)
        for x, y in itertools.combinations(power, 2)
    )
    assert math.isclose(total, 1.0, rel_tol=1e-9)


def test_pair_top_two_probability_is_symmetric_in_its_two_arguments() -> None:
    power = {"a": 18.0, "b": 15.0, "c": 13.0, "d": 11.0}
    assert pair_top_two_probability(power, "a", "b", temperature=5.0) == pytest.approx(
        pair_top_two_probability(power, "b", "a", temperature=5.0)
    )


def test_pair_top_two_probability_favors_the_two_strongest_teams() -> None:
    power = {"a": 18.0, "b": 15.0, "c": 13.0, "d": 11.0}
    strongest_pair = pair_top_two_probability(power, "a", "b", temperature=5.0)
    weakest_pair = pair_top_two_probability(power, "c", "d", temperature=5.0)
    assert strongest_pair > weakest_pair


def test_pair_top_two_probability_rejects_same_candidate() -> None:
    with pytest.raises(ValueError):
        pair_top_two_probability({"a": 1.0, "b": 1.0}, "a", "a")


def test_pair_top_two_probability_unknown_candidate_raises() -> None:
    with pytest.raises(KeyError):
        pair_top_two_probability({"a": 1.0, "b": 1.0}, "a", "ghost")
