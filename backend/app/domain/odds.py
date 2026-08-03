"""Pari-mutuel-with-seed odds for bet markets.

There's no house behind this app at all -- no operator, no bankroll, no commission (see
`services.betting_service`'s settlement, which credits winners without any pool constraining it)
-- so payouts are only meaningful if the crowd's own tokens are what price the market. That's the
classic pari-mutuel setup: everyone's stakes on a given outcome go into a shared pot, and the odds
fall out of how that pot splits, rather than a bookmaker unilaterally setting a price.

A pure pari-mutuel pool breaks down with only a handful of bettors, though: the very first
person to bet on a market has no pool to read a price from, and one $5 bet on a longshot in a
20-person group would otherwise swing that candidate's odds wildly. `pari_mutuel_probability`
fixes both by blending the real pool with a *seed* -- `DEFAULT_SEED` dollars of phantom
liquidity distributed according to a prior probability (`app.services.odds_service`'s
team/speaker/institution "power rating" model, or a flat/uniform prior where no rating data
exists yet). With an empty pool the price is exactly the prior; as real stakes accumulate they
progressively take over, and once total stakes on a market pass the seed, the crowd is what's
actually setting the odds -- the model just breaks the ice.

No margin is taken on top: prices are the fair 1/p, clamped to `[MIN_ODDS, MAX_ODDS]` purely as a
readability guard -- a near-certainty still pays a little more than the stake back, and a
wide-open field (e.g. "any of 40 untested speakers") can't produce an absurd four/five-figure
multiplier just because nobody's bet on it yet.

Two prior shapes cover every bet type in `app.models.enums.BetType`:
  - `softmax_probabilities` -- "who wins among this candidate set" (champion, head_to_head,
    round_winner, best_institution).
  - `sequence_probability` -- "pick these N in this exact order" (top_n_break,
    top_n_speakers), via the Plackett-Luce model: the probability of drawing a specific ordered
    sequence without replacement from a population weighted by `power`, matching how
    exacta/trifecta-style horse-racing markets are priced and the "parlay" framing of "get every
    leg exactly right or the ticket pays nothing."

`single_candidate_odds`/`ordered_sequence_odds` (prior-only, no pool) are kept as the
pure "fair book" building block pari-mutuel pricing is layered on top of -- see
`pari_mutuel_odds`.
"""

import itertools
import math
import random
from collections import defaultdict
from collections.abc import Iterable
from typing import TypeVar

from app.models.enums import BPPosition

CandidateT = TypeVar("CandidateT")

DEFAULT_TEMPERATURE = 1.0
MIN_TEMPERATURE = 1.0

# --- Fair book, no house edge ------------------------------------------------------------------
# Claim is a for-fun, play-token game: there is no house, no operator, and nothing to fund. Every
# token in play came from a player, so taking a cut would only drain the group's collective
# balance for no one's benefit. Odds are therefore the FAIR price, 1/p exactly, with no vig /
# overround / commission applied on top -- the offered prices across a market sum to an implied
# probability of exactly 1.0.

# Sanity band on the decimal odds. This is NOT house-liability protection (there's no house to
# protect) -- it's purely to keep the game readable and the leaderboard meaningful. Without an
# upper bound, a wide-open zero-data field (e.g. "which of 200 untested speakers is exactly 2nd")
# prices at a four-figure multiplier, so one lucky token would dwarf every skilled call ever made.
# The lower bound keeps a near-certainty paying at least a little more than the stake back, so a
# "free money" pick is never literally free.
MIN_ODDS = 1.01
# Lowered from 50.0 (CNADE 2026 Roadmap Pieza 3) -- the real production bug that paid the
# speaker-table market a flat 50x on a wide-open field (commit 796b440) was this clamp doing
# exactly what it was designed to do, on a field with too little real data to price sensibly.
# 20x still rewards a genuine longshot call heavily without letting one lucky pick single-
# handedly define a season the way 50x could.
MAX_ODDS = 20.0

# Dollars of phantom liquidity seeded into every market's pari-mutuel pool, split according to
# the prior probability (see module docstring). Sized to roughly 10x a typical stake so a single
# early bet doesn't swing the price wildly, while a market that's seen real action (total stakes
# approaching or passing this) has the crowd's money doing most of the pricing.
DEFAULT_SEED = 200.0

# Elimination rounds (octofinals -> grand final) get a much thinner seed. A prelim round spreads
# the same crowd over ~15 simultaneous rooms, so any single debate sees little money and needs
# the model to carry the price; an elimination round has a handful of rooms, everyone is watching
# the SAME debates, and stakes per debate are far larger. With DEFAULT_SEED the model would keep
# overriding a genuinely well-informed crowd all the way to close. This is not "no prior" -- with
# an empty pool the price is still exactly the model's (see `pari_mutuel_probability`, where the
# seed cancels out at zero stakes); the seed only sets how fast real money takes over, and here
# it should be fast.
ELIMINATION_SEED = 25.0


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


def positional_probabilities(
    power_by_candidate: dict[CandidateT, float], position: int, *, temperature: float | None = None
) -> dict[CandidateT, float]:
    """Marginal Plackett-Luce probability that EACH candidate finishes EXACTLY at `position`
    (1-indexed) in the eventual full ranking -- e.g. "P(this speaker is exactly 2nd)", not
    "P(this speaker is top-3)". Supports `position` in {1, 2, 3} only: this domain's one use
    case is "top 3, which exact slot" markets (see `top_speaker_position` in
    `app.services.odds_service`), so a general N-deep version isn't implemented.

    Derived by explicit recursive expansion over who occupies the earlier slots, e.g. for
    position 3: P(i is 3rd) = sum over every ordered pair of distinct others (j, k) of
    P(j is 1st) * P(k is 1st | j removed) * P(i is 1st | j, k removed) -- summing over all
    ordered pairs enumerates every way two other candidates could occupy 1st/2nd before i takes
    3rd, mirroring the same sequential "pick, remove, repeat" process `sequence_probability`
    already uses for full-sequence pricing. As a sanity check, summing the returned dict's
    values is always ~1.0 (with N candidates and N >= position, exactly one of them occupies
    that slot), which the domain test suite verifies numerically.

    O(N) for position 1, O(N^2) for position 2, O(N^3) for position 3 -- fine for this app's
    realistic field sizes (at most a few hundred speakers), deliberately not optimized further
    since a closed-form (Newton's-identities-style) reduction would meaningfully complicate the
    code for a market that's rarely priced more than a few times a minute.
    """
    if position not in (1, 2, 3):
        raise ValueError("positional_probabilities only supports position 1, 2, or 3")
    if not power_by_candidate:
        return {}

    temp = temperature if temperature is not None else adaptive_temperature(
        power_by_candidate.values()
    )
    max_power = max(power_by_candidate.values())
    weights = {
        candidate: math.exp((power - max_power) / temp)
        for candidate, power in power_by_candidate.items()
    }
    total = sum(weights.values())

    if position == 1:
        return {candidate: w / total for candidate, w in weights.items()}

    items = list(weights.items())

    if position == 2:
        result = {}
        for i, w_i in items:
            acc = 0.0
            for j, w_j in items:
                if j == i:
                    continue
                remaining = total - w_j
                if remaining <= 0:
                    continue
                acc += (w_j / total) * (w_i / remaining)
            result[i] = acc
        return result

    # position == 3
    result = {}
    for i, w_i in items:
        acc = 0.0
        for j, w_j in items:
            if j == i:
                continue
            remaining_after_j = total - w_j
            if remaining_after_j <= 0:
                continue
            p_j_first = w_j / total
            for k, w_k in items:
                if k in (i, j):
                    continue
                remaining_after_jk = remaining_after_j - w_k
                if remaining_after_jk <= 0:
                    continue
                p_k_second_given_j = w_k / remaining_after_j
                p_i_third = w_i / remaining_after_jk
                acc += p_j_first * p_k_second_given_j * p_i_third
        result[i] = acc
    return result


DEFAULT_POSITIONAL_SIMULATIONS = 1500


def simulate_positional_probabilities(
    power_by_candidate: dict[CandidateT, float],
    max_position: int,
    *,
    temperature: float | None = None,
    num_simulations: int = DEFAULT_POSITIONAL_SIMULATIONS,
    seed: str = "positional-sim",
) -> dict[int, dict[CandidateT, float]]:
    """Monte Carlo estimate of `positional_probabilities` for positions beyond what the exact
    recursive formula can reach -- see that function's docstring: it's O(N^position) by
    construction, fine through position 3 but intractable past it for a realistic speaker field
    (a few hundred candidates). Same "simulate the whole field, tally outcomes" pattern
    `app.domain.break_predictor` already uses for an analogous problem (there: final standings
    via points draws; here: full rankings via Plackett-Luce).

    Each trial draws the field's first `max_position` places via the exact same sequential
    weighted-without-replacement process `positional_probabilities` sums over in closed form:
    pick one candidate weighted by softmax(power/temperature) among those not yet picked, remove
    them, repeat. This IS the Plackett-Luce generative process (not an approximation of it), so
    averaging enough trials converges to the same probabilities the exact formula would give --
    verified in tests against `positional_probabilities` for positions 1-3, where both are
    available.

    Returns `{position: {candidate: probability}}` for every position in `1..max_position`, from
    ONE shared simulation run -- callers needing several positions (e.g. pricing an entire
    "top 10" market board) should request them together rather than re-simulating per position,
    the same reason `build_break_report` runs one shared field simulation instead of one per team.

    Deterministic for a given `seed` (default fixed, like `break_predictor`'s own hardcoded
    seeds) -- this is a pricing model, not a fairness-critical draw, so reproducible output
    across calls with the same inputs is more valuable here than per-call randomness.
    """
    if max_position < 1:
        raise ValueError("max_position must be at least 1")
    if not power_by_candidate:
        return {}
    temp = temperature if temperature is not None else adaptive_temperature(
        power_by_candidate.values()
    )
    max_power = max(power_by_candidate.values())
    base_weights = {
        candidate: math.exp((power - max_power) / temp)
        for candidate, power in power_by_candidate.items()
    }
    depth = min(max_position, len(base_weights))

    rank_counts: dict[int, dict[CandidateT, int]] = {
        position: defaultdict(int) for position in range(1, max_position + 1)
    }
    rng = random.Random(seed)
    for _ in range(num_simulations):
        remaining = dict(base_weights)
        for position in range(1, depth + 1):
            pick = rng.choices(
                list(remaining.keys()), weights=list(remaining.values()), k=1
            )[0]
            rank_counts[position][pick] += 1
            del remaining[pick]

    return {
        position: {candidate: count / num_simulations for candidate, count in counts.items()}
        for position, counts in rank_counts.items()
    }


def top_n_probabilities(
    power_by_candidate: dict[CandidateT, float], n: int, *, temperature: float | None = None
) -> dict[CandidateT, float]:
    """P(each candidate finishes in the top `n`) -- i.e. "does this team ADVANCE", the actual
    proposition in a British Parliamentary elimination room where `n` of the 4 teams go through
    (2 for octofinals/quarters/semis, 1 for the grand final).

    Summing `positional_probabilities` over slots 1..n is exact, not an approximation: finishing
    top-n means occupying exactly one of those mutually exclusive slots.

    Unlike every other prior in this module, the returned values sum to ~`n` across the field,
    NOT to 1.0 -- because `n` candidates win, not one. Callers blending this into a pari-mutuel
    pool must divide by `n` first (so priors and stake shares are on the same 1.0 scale) and
    multiply the blended result back by `n`; see `app.services.odds_service`'s ROUND_WINNER
    branch. Pricing these as though only one team advanced is what made backing all four teams
    in an elimination room a risk-free double-your-money arbitrage.
    """
    if n not in (1, 2, 3):
        raise ValueError("top_n_probabilities only supports n of 1, 2, or 3")
    if not power_by_candidate:
        return {}
    temp = temperature if temperature is not None else adaptive_temperature(
        power_by_candidate.values()
    )
    totals = {candidate: 0.0 for candidate in power_by_candidate}
    for position in range(1, n + 1):
        for candidate, probability in positional_probabilities(
            power_by_candidate, position, temperature=temp
        ).items():
            totals[candidate] += probability
    return totals


def pair_top_two_probability(
    power_by_candidate: dict[CandidateT, float],
    a: CandidateT,
    b: CandidateT,
    *,
    temperature: float | None = None,
) -> float:
    """P(candidates `a` and `b` occupy the top 2 slots, in EITHER order) -- the "exact pair
    advances" proposition in a 4-team BP elimination room, where 2 of 4 go through and which
    ONE of them finished ahead of the other doesn't matter for this bet.

    `sequence_probability(power, [x, y])` is the Plackett-Luce marginal P(x is EXACTLY 1st AND y
    is EXACTLY 2nd) -- the sequential draw-without-replacement formula is exact for any ranking
    PREFIX, correctly marginalizing over how the untouched remaining candidates end up ordered.
    Summing both orderings of the pair gives P(the pair occupies the top 2 at all), which is
    exactly what a "does this router of two advance" market needs to price -- as opposed to
    `positional_probabilities`, which answers "does ONE specific candidate land at ONE specific
    slot", not "do these two occupy the two slots together".

    Raises KeyError if either id isn't in `power_by_candidate`, or ValueError if `a == b`.
    """
    if a not in power_by_candidate or b not in power_by_candidate:
        raise KeyError((a, b))
    if a == b:
        raise ValueError("a and b must be different candidates")
    temp = temperature if temperature is not None else adaptive_temperature(
        power_by_candidate.values()
    )
    return sequence_probability(
        power_by_candidate, [a, b], temperature=temp
    ) + sequence_probability(power_by_candidate, [b, a], temperature=temp)


def decimal_odds_from_probability(probability: float) -> float:
    """"Pays 1.85x"-style decimal odds: stake * odds = total returned (including the stake
    itself) if the bet wins.

    This is the fair price, 1/p exactly -- no house margin is taken (see the "Fair book" note
    above) -- clamped to [MIN_ODDS, MAX_ODDS] as a readability guard only."""
    p = min(max(probability, 0.0), 1.0)
    if p <= 0.0:
        return MAX_ODDS
    return round(min(max(1.0 / p, MIN_ODDS), MAX_ODDS), 2)


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


def sequence_probability(
    power_by_candidate: dict[CandidateT, float],
    sequence: list[CandidateT],
    *,
    temperature: float | None = None,
) -> float:
    """Probability of drawing `sequence` in that EXACT order (Plackett-Luce): the probability of
    picking sequence[0] first from the full field, times the probability of picking sequence[1]
    first from the field with sequence[0] removed, and so on.

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

    return combined_probability


def exact_rank_gap_probability(
    power_by_candidate: dict[CandidateT, float],
    higher_id: CandidateT,
    lower_id: CandidateT,
    gap: int,
    *,
    temperature: float | None = None,
) -> float:
    """P(`higher_id` finishes EXACTLY `gap` positions above `lower_id` | `higher_id` finishes
    above `lower_id` at all) over the full field in `power_by_candidate` (this domain's one use
    case is a single 4-team BP debate -- see `round_head_to_head` in
    `app.services.odds_service`). Conditioned on the base pick already being correct, matching
    the "combined odds = base_odds * modifier_odds" chain-rule pricing this sub-bet uses: the
    modifier's own price only needs to answer "given you already need `higher_id` to win, how
    much MORE precise do you also need to be."

    Brute-forced by enumerating every full-field permutation and weighting each by
    `sequence_probability` -- deliberately not a closed form. The field here is always small
    (4 BP teams = 24 permutations), so there's no performance reason to derive one, and brute
    force is trivially correct to read and verify.

    Raises KeyError if either id isn't in `power_by_candidate`, or ValueError if `gap` is
    outside `[1, len(power_by_candidate) - 1]` or `higher_id == lower_id`.
    """
    candidates = list(power_by_candidate)
    if higher_id not in candidates or lower_id not in candidates:
        raise KeyError((higher_id, lower_id))
    if higher_id == lower_id:
        raise ValueError("higher_id and lower_id must be different candidates")
    if not (1 <= gap <= len(candidates) - 1):
        raise ValueError(f"gap must be between 1 and {len(candidates) - 1}")

    temp = temperature if temperature is not None else adaptive_temperature(
        power_by_candidate.values()
    )
    higher_wins_total = 0.0
    higher_wins_with_gap = 0.0
    for perm in itertools.permutations(candidates):
        rank = {candidate: i + 1 for i, candidate in enumerate(perm)}
        if rank[higher_id] >= rank[lower_id]:
            continue  # higher_id did not actually rank above lower_id in this permutation
        probability = sequence_probability(power_by_candidate, list(perm), temperature=temp)
        higher_wins_total += probability
        if rank[lower_id] - rank[higher_id] == gap:
            higher_wins_with_gap += probability

    if higher_wins_total <= 0:
        return 0.0
    return higher_wins_with_gap / higher_wins_total


def ordered_sequence_odds(
    power_by_candidate: dict[CandidateT, float],
    sequence: list[CandidateT],
    *,
    temperature: float | None = None,
) -> float:
    """Fair-book (no pool) combined decimal odds for drawing `sequence` in that EXACT order --
    the "parlay" price: getting 2 of 3 legs right pays nothing, same as a real exacta/trifecta.
    See `sequence_probability` for the underlying probability and error conditions."""
    return decimal_odds_from_probability(
        sequence_probability(power_by_candidate, sequence, temperature=temperature)
    )


def pari_mutuel_probability(
    candidate_stake: float,
    compartment_stake: float,
    prior_probability: float,
    *,
    seed: float = DEFAULT_SEED,
) -> float:
    """Blends real money (`candidate_stake` out of `compartment_stake` total, both in dollars
    already staked on OPEN predictions) with `seed` dollars of phantom liquidity distributed per
    `prior_probability` -- see module docstring. With no stakes yet this is exactly
    `prior_probability`; as `compartment_stake` grows past `seed`, the crowd's money dominates.

    `compartment_stake` is the total across every candidate in the same "compartment" the
    candidate belongs to -- the whole market for most bet types, but e.g. just the two teams in
    one specific head-to-head pairing, or one specific debate's participants, when a market
    covers many independent pairings/debates. `candidate_stake` must be `<= compartment_stake`.
    """
    if seed <= 0:
        raise ValueError("seed must be positive")
    if candidate_stake < 0 or compartment_stake < 0:
        raise ValueError("stakes must not be negative")
    if candidate_stake > compartment_stake:
        raise ValueError("candidate_stake cannot exceed compartment_stake")
    return (candidate_stake + seed * prior_probability) / (compartment_stake + seed)


# Default weight of the positional-history term relative to the field's own power spread (see
# `apply_positional_adjustment`) -- kept deliberately modest. This is a prior nudge, not a
# replacement for the field's own results: even a position with a strongly one-sided historical
# win rate should tilt the price, not dominate it the way a team's own accumulated points do.
POSITIONAL_ADJUSTMENT_WEIGHT = 0.5


def apply_positional_adjustment(
    power_by_candidate: dict[CandidateT, float],
    position_by_candidate: dict[CandidateT, BPPosition],
    win_rate_by_position: dict[BPPosition, float],
    *,
    weight: float = POSITIONAL_ADJUSTMENT_WEIGHT,
) -> dict[CandidateT, float]:
    """Nudges each candidate's power score by how well its BP position (OG/OO/CG/CO) has
    historically done in this kind of round -- see CNADE 2026 Roadmap Pieza 2b. Purely additive
    to the SAME power dict `softmax_probabilities`/`top_n_probabilities` already consume, so it
    composes with every existing pricing path without changing their shape.

    Scaled by the field's own spread (`adaptive_temperature`) rather than a fixed constant, for
    the same reason `adaptive_temperature` itself exists: team_points, speaker_points, and this
    positional win rate are all on different unit scales, so "one std of the field" is the only
    scale-free way to size the nudge consistently across tournaments and bet types.

    Guaranteed a no-op with no historical data yet: `win_rate_by_position` defaults every
    position to 0.25 when nothing has been observed (see positional_stats_service), and adding
    the SAME constant to every candidate's score is invariant under softmax -- so this function
    changes nothing until real backfilled position/round data exists to compute real rates from.
    """
    if not power_by_candidate:
        return power_by_candidate
    spread = adaptive_temperature(power_by_candidate.values())
    return {
        candidate: power
        + weight * spread * win_rate_by_position.get(position_by_candidate[candidate], 0.25)
        for candidate, power in power_by_candidate.items()
    }


def pari_mutuel_odds(
    candidate_stake: float,
    compartment_stake: float,
    prior_probability: float,
    *,
    seed: float = DEFAULT_SEED,
) -> float:
    """Decimal odds from blending the real pool with the seeded prior -- see
    `pari_mutuel_probability` and the module docstring."""
    return decimal_odds_from_probability(
        pari_mutuel_probability(
            candidate_stake, compartment_stake, prior_probability, seed=seed
        )
    )
