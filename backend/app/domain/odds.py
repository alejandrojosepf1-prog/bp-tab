"""Fixed-odds pricing for bet markets, computed from each candidate's "power rating" (how
strong a team/speaker/institution looks right now -- see `app.services.odds_service` for how
that rating is actually built from standings + strength of schedule).

This is a *sportsbook* model, not a pari-mutuel pool: odds are priced from the candidates'
relative strength the moment a prediction is placed and locked onto that `Prediction` row, so a
later flood of money on a favorite never moves an already-placed bet's payout. `BetMarket`'s
displayed "pool" (sum of everyone's stakes) is informational flavor only -- it does not feed
back into the odds math, unlike a real pari-mutuel/parimutuel pool.

A house margin ("vig"/overround) IS applied: every fair 1/p price is shaved by
`HOUSE_MARGIN` so the implied probabilities across a market sum to >1.0, giving the book a
positive expected hold no matter which outcome lands. Offered odds are also clamped to a
realistic `[MIN_ODDS, MAX_ODDS]` band -- a near-certainty still pays a little rather than
~1.00, and an extreme longshot can't produce the absurd/unbounded payout a raw 1/p would.

Two shapes cover every bet type in `app.models.enums.BetType`:
  - `single_candidate_odds` -- "who wins among this candidate set" (champion, head_to_head,
    round_winner, best_institution, breakout_team).
  - `ordered_sequence_odds` -- "pick these N in this exact order" (top_n_break,
    top_n_speakers), priced via the Plackett-Luce model: the probability of drawing a specific
    ordered sequence without replacement from a population weighted by `power`, which is exactly
    how exacta/trifecta-style horse-racing markets are priced and matches the "parley" (parlay)
    framing of "get every leg exactly right or the ticket pays nothing."
"""

import math
from collections.abc import Iterable
from typing import TypeVar

CandidateT = TypeVar("CandidateT")

DEFAULT_TEMPERATURE = 1.0
MIN_TEMPERATURE = 1.0

# --- House economics -------------------------------------------------------------------------
# Unlike a play-money predictions game, a real book has to hold an edge. We inflate the implied
# probability by HOUSE_MARGIN (equivalently: divide the fair 1/p odds by 1 + HOUSE_MARGIN) so
# the offered prices across a market sum to an implied probability >1.0 -- the "overround" that
# guarantees the house a positive expected margin regardless of who wins. 0.07 = a 7% hold,
# squarely in real-sportsbook territory (typically 5-10%).
HOUSE_MARGIN = 0.07

# Realistic decimal-odds band. A real book never offers 10000x (it caps longshots to bound its
# liability) and never prices a near-certainty at ~1.00 (no action / boring). MAX_ODDS = 51.0 is
# a "big longshot" ceiling (~2% implied), not a lottery ticket; MIN_ODDS keeps favorites paying
# a little more than the stake back.
MIN_ODDS = 1.02
MAX_ODDS = 51.0


def softmax_probabilities(
    power_by_candidate: dict[CandidateT, float], *, temperature: float = DEFAULT_TEMPERATURE
) -> dict[CandidateT, float]:
    """Converts power ratings into win probabilities that sum to 1.0 across the candidate set.

    `temperature` controls how sharply the favorite is favored: lower = more lopsided odds
    (rewards being the clear favorite), higher = closer to a flat coin-toss across the field
    regardless of the power gap. 1.0 is a reasonable, unexaggerated default.
    """
    if not power_by_candidate:
        return {}
    if temperature <= 0:
        raise ValueError("temperature must be positive")

    # Subtract the max before exponentiating (standard softmax stabilization) so this can't
    # overflow even with large power ratings.
    max_power = max(power_by_candidate.values())
    weights = {
        candidate: math.exp((power - max_power) / temperature)
        for candidate, power in power_by_candidate.items()
    }
    total = sum(weights.values())
    return {candidate: weight / total for candidate, weight in weights.items()}


def adaptive_temperature(power_values: Iterable[float]) -> float:
    """Softmax temperature scaled to the field's own spread, so pricing is realistic regardless
    of the power metric's units (team_points span ~0-24, speaker-point totals span hundreds,
    institution sums are larger still). A fixed temperature would make a few-point gap look like
    a 99% favorite on the team_points scale while barely moving the odds on the speaker scale.

    Using the population standard deviation of the ratings means "one std above the field" prices
    to roughly the same favoritism on every scale. Floored at MIN_TEMPERATURE so a field with
    (near-)zero spread -- e.g. a brand-new tournament where every rating is still 0 -- collapses
    to a sensible uniform market instead of dividing by ~0.
    """
    vals = list(power_values)
    if len(vals) < 2:
        return MIN_TEMPERATURE
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    return max(MIN_TEMPERATURE, math.sqrt(variance))


def decimal_odds_from_probability(probability: float) -> float:
    """"Pays 1.85x"-style decimal odds: stake * odds = total returned (including the stake
    itself) if the bet wins.

    The fair 1/p price is divided by (1 + HOUSE_MARGIN) so the book holds ~HOUSE_MARGIN in
    expectation on every outcome (this is what makes it a profitable book, not a break-even
    one), then clamped to [MIN_ODDS, MAX_ODDS] so a near-certainty still pays a little and an
    extreme longshot can't produce an absurd/unbounded payout."""
    p = min(max(probability, 0.0), 1.0)
    if p <= 0.0:
        return MAX_ODDS
    offered = (1.0 / p) / (1.0 + HOUSE_MARGIN)
    return round(min(max(offered, MIN_ODDS), MAX_ODDS), 2)


def single_candidate_odds(
    power_by_candidate: dict[CandidateT, float],
    candidate: CandidateT,
    *,
    temperature: float | None = None,
) -> float:
    """Decimal odds for `candidate` to be the one winner among `power_by_candidate`'s full
    field. Raises KeyError if `candidate` isn't in the field -- callers should validate the pick
    refers to a real, currently-tracked team/speaker/institution before pricing it.

    `temperature=None` (the default) derives it from the field's own spread via
    `adaptive_temperature`; pass an explicit value only to override that (e.g. in tests)."""
    if candidate not in power_by_candidate:
        raise KeyError(candidate)
    temp = temperature if temperature is not None else adaptive_temperature(
        power_by_candidate.values()
    )
    probabilities = softmax_probabilities(power_by_candidate, temperature=temp)
    return decimal_odds_from_probability(probabilities[candidate])


def ordered_sequence_odds(
    power_by_candidate: dict[CandidateT, float],
    sequence: list[CandidateT],
    *,
    temperature: float | None = None,
) -> float:
    """Combined decimal odds for drawing `sequence` in that EXACT order (Plackett-Luce): the
    probability of picking sequence[0] first from the full field, times the probability of
    picking sequence[1] first from the field with sequence[0] removed, and so on. This is the
    "parlay" price -- getting 2 of 3 legs right pays nothing, same as a real exacta/trifecta.

    Raises KeyError if any entry of `sequence` isn't in `power_by_candidate`, or ValueError if
    `sequence` has duplicates or is empty.
    """
    if not sequence:
        raise ValueError("sequence must not be empty")
    if len(set(sequence)) != len(sequence):
        raise ValueError("sequence must not contain duplicates")

    # Temperature is derived once from the full field and reused for every leg, so the market's
    # "sharpness" stays constant as candidates are removed step by step (rather than drifting as
    # the remaining field shrinks).
    temp = temperature if temperature is not None else adaptive_temperature(
        power_by_candidate.values()
    )
    remaining = dict(power_by_candidate)
    combined_probability = 1.0
    for pick in sequence:
        if pick not in remaining:
            raise KeyError(pick)
        step_probabilities = softmax_probabilities(remaining, temperature=temp)
        combined_probability *= step_probabilities[pick]
        del remaining[pick]

    return decimal_odds_from_probability(combined_probability)
