"""Fixed-odds pricing for bet markets, computed from each candidate's "power rating" (how
strong a team/speaker/institution looks right now -- see `app.services.odds_service` for how
that rating is actually built from standings + strength of schedule).

This is a *sportsbook* model, not a pari-mutuel pool: odds are priced from the candidates'
relative strength the moment a prediction is placed and locked onto that `Prediction` row, so a
later flood of money on a favorite never moves an already-placed bet's payout. `BetMarket`'s
displayed "pool" (sum of everyone's stakes) is informational flavor only -- it does not feed
back into the odds math, unlike a real pari-mutuel/parimutuel pool.

No "vig"/overround is subtracted (implied probabilities are used as-is, summing to ~1.0):
there's no house to protect since nothing here is real money, and skipping it makes every
market pay out exactly what its computed odds promise.

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
from typing import TypeVar

CandidateT = TypeVar("CandidateT")

MIN_PROBABILITY = 0.0001  # floor so an extreme outlier can't produce an infinite/absurd payout
DEFAULT_TEMPERATURE = 1.0


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


def decimal_odds_from_probability(probability: float) -> float:
    """"Pays 1.85x"-style decimal odds: stake * odds = total returned (including the stake
    itself) if the bet wins. A pure 1/p conversion, floored so a near-certain outcome still
    returns slightly more than the stake rather than an odds of ~1.00 (boring) or the
    unbounded/undefined odds a literal p=0 would produce."""
    clamped = max(probability, MIN_PROBABILITY)
    return round(1.0 / clamped, 2)


def single_candidate_odds(
    power_by_candidate: dict[CandidateT, float],
    candidate: CandidateT,
    *,
    temperature: float = DEFAULT_TEMPERATURE,
) -> float:
    """Decimal odds for `candidate` to be the one winner among `power_by_candidate`'s full
    field. Raises KeyError if `candidate` isn't in the field -- callers should validate the pick
    refers to a real, currently-tracked team/speaker/institution before pricing it."""
    if candidate not in power_by_candidate:
        raise KeyError(candidate)
    probabilities = softmax_probabilities(power_by_candidate, temperature=temperature)
    return decimal_odds_from_probability(probabilities[candidate])


def ordered_sequence_odds(
    power_by_candidate: dict[CandidateT, float],
    sequence: list[CandidateT],
    *,
    temperature: float = DEFAULT_TEMPERATURE,
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

    remaining = dict(power_by_candidate)
    combined_probability = 1.0
    for pick in sequence:
        if pick not in remaining:
            raise KeyError(pick)
        step_probabilities = softmax_probabilities(remaining, temperature=temperature)
        combined_probability *= step_probabilities[pick]
        del remaining[pick]

    return decimal_odds_from_probability(combined_probability)
