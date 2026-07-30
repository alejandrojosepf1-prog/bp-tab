"""Builds the "power rating" each candidate (team/speaker/institution) needs before
`app.domain.odds` can price a market, and dispatches pricing per `BetType`.

A team's power rating combines three signals, each already available from data this app already
tracks -- nothing here invents a new stat:
  - `team_points`: the standard BP tournament-points metric (see `domain.ranking`).
  - `total_speaker_points`, lightly weighted, as a tiebreak/secondary skill signal for teams
    that are close on team_points alone.
  - Strength of schedule: the average `team_points` of every opponent this team has actually
    debated against so far, lightly weighted -- a team that's 4-0 against strong opponents
    should price as a stronger favorite than a team that's 4-0 against weak ones, which plain
    team_points can't distinguish on its own. This is the "contra quién se han enfrentado" part.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.odds import (
    ELIMINATION_SEED,
    adaptive_temperature,
    decimal_odds_from_probability,
    exact_rank_gap_probability,
    pair_top_two_probability,
    pari_mutuel_odds,
    pari_mutuel_probability,
    positional_probabilities,
    sequence_probability,
    softmax_probabilities,
    top_n_probabilities,
)
from app.models import (
    BetMarket,
    Debate,
    DebateTeam,
    Institution,
    Prediction,
    Round,
    Speaker,
    SpeakerScore,
    Team,
    TeamBreakCategory,
)
from app.models.enums import BetType, PredictionStatus, RoundStage
from app.services.break_service import team_break_exact_rank_probability, team_break_probability
from app.services.ranking_service import get_standings

SPEAKER_POINTS_WEIGHT = 0.02  # total_speaker_points are ~10-30x team_points in magnitude
STRENGTH_OF_SCHEDULE_WEIGHT = 0.5

# BREAKOUT_TEAM ("equipo revelación") has no principled strength-based price -- picking the
# team that most exceeds ITS OWN prior expectation is a qualitative judgment call (see
# services/betting_service.py's build_market_outcome docstring for the same caveat on
# settlement), so it gets a flat, admin-tunable default instead of a computed one.
DEFAULT_BREAKOUT_TEAM_ODDS = 4.0

# team_break's "exact_points" sub-bet modifier (the team's EXACT team_points total at the
# moment the break is decided) has the same problem: there's no historical data on how
# team_points are distributed across the field to build a real probability from, and the value
# itself is close to a coin-flip-times-many-outcomes guess. Same pattern as
# DEFAULT_BREAKOUT_TEAM_ODDS -- a flat, admin-tunable multiplier rather than invented
# statistics. Kept notably higher than DEFAULT_BREAKOUT_TEAM_ODDS since guessing one exact
# integer point total is a much longer shot than picking one team out of a field.
DEFAULT_EXACT_POINTS_SUB_BET_ODDS = 8.0

# round_winner's "speaker points" sub-bet (see betting_service.settle_pending_sub_bets for the
# deferred-settlement mechanics) asks for TWO independent exact speaker scores at once, on top
# of the base pick already needing that team to win the room -- a much longer shot than
# team_break's single exact_points guess above, so it's priced notably higher on the same flat,
# admin-tunable pattern (no historical distribution of speaker scores to build a real
# probability from either).
DEFAULT_SPEAKER_POINTS_SUB_BET_ODDS = 15.0


class UnpriceableMarketError(Exception):
    """Raised when a market/payload combination can't be priced yet (e.g. no debates played
    so there's no standings data to build a power rating from). Callers should surface this as
    a 400 -- betting can't open on a market with nothing to price odds from."""


async def _open_stakes(
    session: AsyncSession, market_id: int, *, exclude_user_id: int | None = None
) -> list[tuple[dict, float]]:
    """(payload, stake_amount) for every currently-OPEN prediction on this market -- the live
    pari-mutuel pool. Settled predictions are excluded: once a market closes its pool is frozen
    anyway (no new bets), so this only ever matters pre-close, and staying OPEN-only keeps a
    settled market's history from double-counting if this were ever called after the fact.

    `exclude_user_id` leaves out that user's own current stake -- callers pass the quoting
    user's id so that re-quoting an existing bet (editing your pick, or the live preview doing
    the same math before you submit) doesn't let your own prior stake inflate/deflate your own
    price. `place_prediction` already refunds that same prior stake before charging the new one;
    this is the pricing-side mirror of that so a resubmit-with-the-same-pick is a no-op on price,
    not a self-reinforcing one."""
    conditions = [
        Prediction.bet_market_id == market_id,
        Prediction.status == PredictionStatus.OPEN,
    ]
    if exclude_user_id is not None:
        conditions.append(Prediction.user_id != exclude_user_id)
    rows = (
        await session.execute(
            select(Prediction.payload, Prediction.stake_amount).where(*conditions)
        )
    ).all()
    return [(payload, float(stake)) for payload, stake in rows]


def _field_pool_from_stakes(
    open_stakes: list[tuple[dict, float]], field: str, candidate_value: object
) -> tuple[float, float]:
    """(stake on `candidate_value`, total stake across the whole market) for a market where
    every prediction competes in one shared pool -- champion, best_institution. Pure/in-memory
    over an already-fetched `open_stakes` list, so a caller pricing many payloads at once (see
    `market_board`'s generic fallback) can fetch stakes ONCE instead of once per payload."""
    candidate_stake = 0.0
    total = 0.0
    for payload, stake in open_stakes:
        total += stake
        if payload.get(field) == candidate_value:
            candidate_stake += stake
    return candidate_stake, total


async def _field_pool(
    session: AsyncSession,
    market_id: int,
    field: str,
    candidate_value: object,
    *,
    exclude_user_id: int | None,
) -> tuple[float, float]:
    stakes = await _open_stakes(session, market_id, exclude_user_id=exclude_user_id)
    return _field_pool_from_stakes(stakes, field, candidate_value)


def _pair_pool_from_stakes(
    open_stakes: list[tuple[dict, float]],
    team_a_id: int,
    team_b_id: int,
    predicted_winner_id: int,
    *,
    predicted_field: str = "predicted_winner_id",
    debate_id: int | None = None,
) -> tuple[float, float]:
    """Same as `_field_pool_from_stakes`, but scoped to just this one head-to-head pairing -- a
    HEAD_TO_HEAD-style market can host many independent pairings, so team A vs. B's money
    shouldn't dilute or be diluted by C vs. D's. `predicted_field` lets ROUND_HEAD_TO_HEAD reuse
    this same pool logic under its own payload key (`predicted_higher_id`) instead of legacy
    HEAD_TO_HEAD's `predicted_winner_id`; `debate_id`, when given, additionally scopes to one
    specific drawn debate (redundant in practice -- two teams can only co-occur in one debate
    within a single round-scoped market -- but cheap and matches entity_key's own scoping)."""
    pair = {team_a_id, team_b_id}
    candidate_stake = 0.0
    total = 0.0
    for payload, stake in open_stakes:
        a, b = payload.get("team_a_id"), payload.get("team_b_id")
        if a is None or b is None or {a, b} != pair:
            continue
        if debate_id is not None and payload.get("debate_id") != debate_id:
            continue
        total += stake
        if payload.get(predicted_field) == predicted_winner_id:
            candidate_stake += stake
    return candidate_stake, total


async def _pair_pool(
    session: AsyncSession,
    market_id: int,
    team_a_id: int,
    team_b_id: int,
    predicted_winner_id: int,
    *,
    exclude_user_id: int | None,
    predicted_field: str = "predicted_winner_id",
    debate_id: int | None = None,
) -> tuple[float, float]:
    stakes = await _open_stakes(session, market_id, exclude_user_id=exclude_user_id)
    return _pair_pool_from_stakes(
        stakes,
        team_a_id,
        team_b_id,
        predicted_winner_id,
        predicted_field=predicted_field,
        debate_id=debate_id,
    )


def _debate_pool_from_stakes(
    open_stakes: list[tuple[dict, float]], debate_id: int, team_id: int
) -> tuple[float, float]:
    """Same idea as `_pair_pool_from_stakes`, scoped to one debate -- a ROUND_WINNER market can
    span many debates in a round."""
    candidate_stake = 0.0
    total = 0.0
    for payload, stake in open_stakes:
        if payload.get("debate_id") != debate_id:
            continue
        total += stake
        if payload.get("team_id") == team_id:
            candidate_stake += stake
    return candidate_stake, total


async def _debate_pool(
    session: AsyncSession,
    market_id: int,
    debate_id: int,
    team_id: int,
    *,
    exclude_user_id: int | None,
) -> tuple[float, float]:
    stakes = await _open_stakes(session, market_id, exclude_user_id=exclude_user_id)
    return _debate_pool_from_stakes(stakes, debate_id, team_id)


async def _advancing_count(session: AsyncSession, debate_id: int) -> int | None:
    """How many of this debate's teams ADVANCE, if it belongs to an elimination round -- or
    `None` when it's an ordinary preliminary debate (exactly one "winner", the team that ranks
    1st).

    British Parliamentary elimination rooms send 2 of 4 teams through, except the grand final
    which crowns 1. The tab never publishes "how many advance" as a field, so it's inferred from
    the round's shape: a round with a single debate is the final, anything wider is a normal
    2-per-room elimination round.

    ponytail: debate-count heuristic, covers standard BP brackets. If a tournament ever runs a
    partial-double-octofinal (uneven bracket where some rooms advance 1 and others 2), read the
    real count off the next round's team count instead.
    """
    row = (
        await session.execute(
            select(Round.id, Round.stage)
            .join(Debate, Debate.round_id == Round.id)
            .where(Debate.id == debate_id)
        )
    ).first()
    if row is None or row.stage != RoundStage.ELIMINATION:
        return None
    num_debates = (
        await session.execute(
            select(func.count(Debate.id)).where(Debate.round_id == row.id)
        )
    ).scalar_one()
    return 1 if num_debates <= 1 else 2


def _round_winner_odds(
    debate_power: dict[int, float],
    team_id: int,
    *,
    temperature: float,
    candidate_stake: float,
    compartment_stake: float,
    advancing_count: int | None,
) -> float:
    """Price for "this team wins/advances out of its debate". Shared by `quote_odds` and
    `market_board`'s fallback so the two can never drift apart (see `_generic_fallback_options`).

    Preliminary rounds (`advancing_count is None`) are a one-winner market: the softmax prior
    sums to 1 across the room and blends straight into the seeded pari-mutuel pool.

    Elimination rounds are a TOP-N market -- `advancing_count` teams advance together, so
    P(advance) sums to `advancing_count`, not 1. Blending that directly against pool shares
    (which always sum to 1) is what mispriced every elimination room by a factor of
    `advancing_count`, making "back all four teams" a guaranteed double-up. Instead the prior is
    normalized to the 1.0 scale, blended, then scaled back up -- which is also exactly how a real
    pari-mutuel place pool pays: the pool splits between the N winners, so each winner's backers
    collect `1 / (N * their_share)`.
    """
    if advancing_count is None:
        prior = softmax_probabilities(debate_power, temperature=temperature)[team_id]
        return pari_mutuel_odds(candidate_stake, compartment_stake, prior)

    prior_advance = top_n_probabilities(debate_power, advancing_count, temperature=temperature)[
        team_id
    ]
    blended = pari_mutuel_probability(
        candidate_stake,
        compartment_stake,
        prior_advance / advancing_count,
        seed=ELIMINATION_SEED,
    )
    return decimal_odds_from_probability(min(1.0, blended * advancing_count))


async def _require_debate_in_round(
    session: AsyncSession, debate_id: int, target_round_id: int | None
) -> None:
    """Round-scoped markets (`round_winner`, `round_full_call`) are created against one specific
    round via `target_round_id` -- this stops a payload from naming a debate out of a different
    round entirely. Skipped for `target_round_id is None` so markets created before this field
    was required (or before this constraint existed) keep working unmodified."""
    if target_round_id is None:
        return
    round_id = (
        await session.execute(select(Debate.round_id).where(Debate.id == debate_id))
    ).scalar_one_or_none()
    if round_id != target_round_id:
        raise ValueError("ese debate no pertenece a la ronda de este mercado")


def _debate_sequence_pool_from_stakes(
    open_stakes: list[tuple[dict, float]], debate_id: int, team_ids: list[int]
) -> tuple[float, float]:
    """Like `_debate_pool_from_stakes` (compartment = this one debate's money, since a
    `round_full_call` market can span every debate in a round) combined with
    `_sequence_pool_from_stakes`'s exact-match candidate rule (many different orderings can be
    guessed for the same debate)."""
    target = tuple(team_ids)
    candidate_stake = 0.0
    total = 0.0
    for payload, stake in open_stakes:
        if payload.get("debate_id") != debate_id:
            continue
        ids = payload.get("team_ids")
        if not ids:
            continue
        total += stake
        if tuple(ids) == target:
            candidate_stake += stake
    return candidate_stake, total


def _debate_pair_pool_from_stakes(
    open_stakes: list[tuple[dict, float]], debate_id: int, team_ids: tuple[int, int]
) -> tuple[float, float]:
    """Like `_debate_sequence_pool_from_stakes`, but for ROUND_ADVANCING_PAIR: which 2 of the
    4 teams advance TOGETHER, unordered -- {a, b} and {b, a} are the same pick, unlike
    ROUND_FULL_CALL's exact-order sequences. Payloads are compared as sets for that reason."""
    target = frozenset(team_ids)
    candidate_stake = 0.0
    total = 0.0
    for payload, stake in open_stakes:
        if payload.get("debate_id") != debate_id:
            continue
        ids = payload.get("team_ids")
        if not ids or len(ids) != 2:
            continue
        total += stake
        if frozenset(ids) == target:
            candidate_stake += stake
    return candidate_stake, total


async def _debate_pair_pool(
    session: AsyncSession,
    market_id: int,
    debate_id: int,
    team_ids: tuple[int, int],
    *,
    exclude_user_id: int | None,
) -> tuple[float, float]:
    stakes = await _open_stakes(session, market_id, exclude_user_id=exclude_user_id)
    return _debate_pair_pool_from_stakes(stakes, debate_id, team_ids)


async def _debate_sequence_pool(
    session: AsyncSession,
    market_id: int,
    debate_id: int,
    team_ids: list[int],
    *,
    exclude_user_id: int | None,
) -> tuple[float, float]:
    stakes = await _open_stakes(session, market_id, exclude_user_id=exclude_user_id)
    return _debate_sequence_pool_from_stakes(stakes, debate_id, team_ids)


def _speaker_position_pool_from_stakes(
    open_stakes: list[tuple[dict, float]], position: int, speaker_id: int
) -> tuple[float, float]:
    """Compartment = money staked on THIS position (position 1/2/3 are independent coin-flips,
    not one shared 3-way pool -- see `top_speaker_position` in `quote_odds`), candidate = stakes
    naming this exact speaker for it."""
    candidate_stake = 0.0
    total = 0.0
    for payload, stake in open_stakes:
        if payload.get("position") != position:
            continue
        total += stake
        if payload.get("speaker_id") == speaker_id:
            candidate_stake += stake
    return candidate_stake, total


async def _speaker_position_pool(
    session: AsyncSession,
    market_id: int,
    position: int,
    speaker_id: int,
    *,
    exclude_user_id: int | None,
) -> tuple[float, float]:
    stakes = await _open_stakes(session, market_id, exclude_user_id=exclude_user_id)
    return _speaker_position_pool_from_stakes(stakes, position, speaker_id)


def _sequence_pool_from_stakes(
    open_stakes: list[tuple[dict, float]], id_key: str, sequence: list[int]
) -> tuple[float, float]:
    """(stake on this exact ordered sequence, total stake across the whole market) for
    top_n_break/top_n_speakers. In a small group most submitted sequences are unique, so this
    usually degenerates to (0, total) -- the seeded prior still prices it sensibly (see
    `app.domain.odds`); it only starts moving once several people converge on the same pick."""
    target = tuple(sequence)
    candidate_stake = 0.0
    total = 0.0
    for payload, stake in open_stakes:
        ids = payload.get(id_key)
        if not ids:
            continue
        total += stake
        if tuple(ids) == target:
            candidate_stake += stake
    return candidate_stake, total


async def _sequence_pool(
    session: AsyncSession,
    market_id: int,
    id_key: str,
    sequence: list[int],
    *,
    exclude_user_id: int | None,
) -> tuple[float, float]:
    stakes = await _open_stakes(session, market_id, exclude_user_id=exclude_user_id)
    return _sequence_pool_from_stakes(stakes, id_key, sequence)


async def compute_team_power_ratings(
    session: AsyncSession, tournament_id: int, *, break_category_id: int | None = None
) -> dict[int, float]:
    """Every team currently registered in the tournament (or break category) gets a rating --
    including ones with zero debates played yet, at power=0 (an even share of the field) -- so a
    market can be priced from the moment a tournament is created, not just once results exist.
    Teams differentiate as real team_points/speaker_points/opponent strength comes in."""
    team_id_stmt = select(Team.id).where(Team.tournament_id == tournament_id)
    if break_category_id is not None:
        team_id_stmt = team_id_stmt.join(
            TeamBreakCategory, TeamBreakCategory.team_id == Team.id
        ).where(TeamBreakCategory.break_category_id == break_category_id)
    all_team_ids = (await session.execute(team_id_stmt)).scalars().all()
    if not all_team_ids:
        return {}

    standings = await get_standings(session, tournament_id, break_category_id=break_category_id)
    points_by_team = {s.team_id: s.team_points for s in standings}
    speaker_points_by_team = {s.team_id: s.total_speaker_points for s in standings}

    opponents_by_team: dict[int, list[int]] = defaultdict(list)
    rows = (
        await session.execute(
            select(Debate.id, DebateTeam.team_id)
            .join(DebateTeam, DebateTeam.debate_id == Debate.id)
            .join(Round, Debate.round_id == Round.id)
            .where(Round.tournament_id == tournament_id, Round.stage == RoundStage.PRELIMINARY)
        )
    ).all()
    teams_by_debate: dict[int, list[int]] = defaultdict(list)
    for debate_id, team_id in rows:
        teams_by_debate[debate_id].append(team_id)
    for teams_in_debate in teams_by_debate.values():
        for team_id in teams_in_debate:
            opponents_by_team[team_id].extend(t for t in teams_in_debate if t != team_id)

    power: dict[int, float] = {}
    for team_id in all_team_ids:
        opponent_ids = opponents_by_team.get(team_id, [])
        opponent_points = [points_by_team[o] for o in opponent_ids if o in points_by_team]
        avg_opponent_strength = (
            sum(opponent_points) / len(opponent_points) if opponent_points else 0.0
        )
        power[team_id] = (
            points_by_team.get(team_id, 0)
            + speaker_points_by_team.get(team_id, 0.0) * SPEAKER_POINTS_WEIGHT
            + avg_opponent_strength * STRENGTH_OF_SCHEDULE_WEIGHT
        )
    return power


async def compute_speaker_power_ratings(
    session: AsyncSession, tournament_id: int
) -> dict[int, float]:
    """Every speaker registered in the tournament gets a rating, starting at 0 before any
    scores are published (see compute_team_power_ratings's docstring for why)."""
    all_speaker_ids = (
        (await session.execute(select(Speaker.id).where(Speaker.tournament_id == tournament_id)))
        .scalars()
        .all()
    )
    if not all_speaker_ids:
        return {}

    stmt = (
        select(SpeakerScore.speaker_id, SpeakerScore.score)
        .join(DebateTeam, SpeakerScore.debate_team_id == DebateTeam.id)
        .join(Debate, DebateTeam.debate_id == Debate.id)
        .join(Round, Debate.round_id == Round.id)
        .where(Round.tournament_id == tournament_id, SpeakerScore.score.is_not(None))
    )
    totals: dict[int, float] = defaultdict(float)
    for speaker_id, score in (await session.execute(stmt)).all():
        totals[speaker_id] += float(score)
    return {speaker_id: totals.get(speaker_id, 0.0) for speaker_id in all_speaker_ids}


async def compute_institution_power_ratings(
    session: AsyncSession, tournament_id: int
) -> dict[str, float]:
    team_power = await compute_team_power_ratings(session, tournament_id)
    if not team_power:
        return {}
    team_rows = (
        await session.execute(
            select(Team.id, Institution.code)
            .join(Institution, Team.institution_id == Institution.id)
            .where(Team.tournament_id == tournament_id)
        )
    ).all()
    totals: dict[str, float] = defaultdict(float)
    for team_id, institution_code in team_rows:
        totals[institution_code] += team_power.get(team_id, 0.0)
    return dict(totals)


async def quote_odds(
    session: AsyncSession,
    bet_market: BetMarket,
    payload: dict,
    *,
    exclude_user_id: int | None = None,
) -> float:
    """Prices `payload` (a candidate pick, same shape a Prediction.payload would have) against
    the market's bet_type: a prior probability (the power-rating model below) blended with
    whatever's already been staked on OPEN predictions in this market, via
    `app.domain.odds.pari_mutuel_odds` -- see that module's docstring for why. Raises
    UnpriceableMarketError if there's not enough data yet, or KeyError/ValueError (from
    app.domain.odds) if the payload names a candidate outside the currently-tracked field --
    both are caller errors the router turns into 4xx responses.

    `exclude_user_id`: pass the quoting user's id so their own currently-OPEN stake (if any --
    they're editing an existing pick) doesn't count toward the pool it's being priced against --
    see `_open_stakes`."""
    bet_type = bet_market.bet_type

    if bet_type == BetType.BREAKOUT_TEAM:
        # No principled per-team prior exists for "equipo revelación" (see
        # DEFAULT_BREAKOUT_TEAM_ODDS's docstring) so there's nothing to blend a pool against;
        # stays a flat, admin-tunable price.
        return float((bet_market.points_rule or {}).get("odds", DEFAULT_BREAKOUT_TEAM_ODDS))

    if bet_type == BetType.CHAMPION:
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        if not power:
            raise UnpriceableMarketError("no standings yet to price this market from")
        team_id = payload["team_id"]
        prior = softmax_probabilities(power, temperature=adaptive_temperature(power.values()))[
            team_id
        ]
        candidate_stake, market_stake = await _field_pool(
            session, bet_market.id, "team_id", team_id, exclude_user_id=exclude_user_id
        )
        return pari_mutuel_odds(candidate_stake, market_stake, prior)

    if bet_type == BetType.HEAD_TO_HEAD:
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        team_a_id, team_b_id = payload["team_a_id"], payload["team_b_id"]
        pair_power = {
            team_id: power[team_id] for team_id in (team_a_id, team_b_id) if team_id in power
        }
        if len(pair_power) != 2:
            raise UnpriceableMarketError("one or both teams have no standings yet")
        # Temperature is derived from the FULL tournament field, not just this pair -- with only
        # two candidates a 2-point gap and a 10-point gap would otherwise normalize to roughly
        # the same odds (softmax has nothing else to compare the gap against). Pricing "how big a
        # favorite" against the whole field's spread keeps a blowout mismatch pricier than a
        # close one.
        temperature = adaptive_temperature(power.values())
        predicted_winner_id = payload["predicted_winner_id"]
        prior = softmax_probabilities(pair_power, temperature=temperature)[predicted_winner_id]
        candidate_stake, pair_stake = await _pair_pool(
            session,
            bet_market.id,
            team_a_id,
            team_b_id,
            predicted_winner_id,
            exclude_user_id=exclude_user_id,
        )
        return pari_mutuel_odds(candidate_stake, pair_stake, prior)

    if bet_type == BetType.ROUND_WINNER:
        debate_id = payload["debate_id"]
        await _require_debate_in_round(session, debate_id, bet_market.target_round_id)
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        debate_team_ids = (
            (
                await session.execute(
                    select(DebateTeam.team_id).where(DebateTeam.debate_id == debate_id)
                )
            )
            .scalars()
            .all()
        )
        debate_power = {t: power[t] for t in debate_team_ids if t in power}
        if len(debate_power) < 2:
            raise UnpriceableMarketError("not enough priced teams in this debate yet")
        # Same reasoning as HEAD_TO_HEAD above: price this debate's 2-4 teams against the
        # tournament-wide spread, not just amongst themselves.
        temperature = adaptive_temperature(power.values())
        team_id = payload["team_id"]
        candidate_stake, debate_stake = await _debate_pool(
            session, bet_market.id, debate_id, team_id, exclude_user_id=exclude_user_id
        )
        return _round_winner_odds(
            debate_power,
            team_id,
            temperature=temperature,
            candidate_stake=candidate_stake,
            compartment_stake=debate_stake,
            advancing_count=await _advancing_count(session, debate_id),
        )

    if bet_type == BetType.ROUND_FULL_CALL:
        debate_id = payload["debate_id"]
        await _require_debate_in_round(session, debate_id, bet_market.target_round_id)
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        debate_team_ids = (
            (
                await session.execute(
                    select(DebateTeam.team_id).where(DebateTeam.debate_id == debate_id)
                )
            )
            .scalars()
            .all()
        )
        debate_power = {t: power[t] for t in debate_team_ids if t in power}
        if len(debate_power) < len(debate_team_ids) or len(debate_power) < 2:
            raise UnpriceableMarketError("not enough priced teams in this debate yet")
        team_ids = list(payload["team_ids"])
        if set(team_ids) != set(debate_team_ids):
            raise ValueError("team_ids must name exactly this debate's teams, each once")
        # Same tournament-wide-spread reasoning as ROUND_WINNER; sequence_probability applies
        # the Plackett-Luce "pick, remove, repeat" model across the debate's own 4 teams, giving
        # the exact 1st-2nd-3rd-4th ordering's probability.
        temperature = adaptive_temperature(power.values())
        prior = sequence_probability(debate_power, team_ids, temperature=temperature)
        candidate_stake, debate_stake = await _debate_sequence_pool(
            session, bet_market.id, debate_id, team_ids, exclude_user_id=exclude_user_id
        )
        return pari_mutuel_odds(candidate_stake, debate_stake, prior)

    if bet_type == BetType.ROUND_HEAD_TO_HEAD:
        debate_id = payload["debate_id"]
        await _require_debate_in_round(session, debate_id, bet_market.target_round_id)
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        team_a_id, team_b_id = payload["team_a_id"], payload["team_b_id"]
        pair_power = {t: power[t] for t in (team_a_id, team_b_id) if t in power}
        if len(pair_power) != 2:
            raise UnpriceableMarketError("one or both teams have no standings yet")
        # Same tournament-wide-spread reasoning as ROUND_WINNER/legacy HEAD_TO_HEAD above.
        temperature = adaptive_temperature(power.values())
        predicted_higher_id = payload["predicted_higher_id"]
        if predicted_higher_id not in (team_a_id, team_b_id):
            raise ValueError("predicted_higher_id must be one of team_a_id/team_b_id")
        prior = softmax_probabilities(pair_power, temperature=temperature)[predicted_higher_id]
        candidate_stake, pair_stake = await _pair_pool(
            session,
            bet_market.id,
            team_a_id,
            team_b_id,
            predicted_higher_id,
            exclude_user_id=exclude_user_id,
            predicted_field="predicted_higher_id",
            debate_id=debate_id,
        )
        return pari_mutuel_odds(candidate_stake, pair_stake, prior)

    if bet_type == BetType.ROUND_ADVANCING_PAIR:
        debate_id = payload["debate_id"]
        await _require_debate_in_round(session, debate_id, bet_market.target_round_id)
        advancing_count = await _advancing_count(session, debate_id)
        if advancing_count != 2:
            # Not an elimination debate, or a single-room final where only 1 team advances --
            # "which pair advances" isn't a coherent question either way.
            raise UnpriceableMarketError(
                "esta sala no tiene exactamente 2 cupos de avance para un mercado de pareja"
            )
        team_ids = payload["team_ids"]
        if len(team_ids) != 2 or team_ids[0] == team_ids[1]:
            raise ValueError("team_ids must name exactly 2 distinct teams")
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        debate_team_ids = (
            (
                await session.execute(
                    select(DebateTeam.team_id).where(DebateTeam.debate_id == debate_id)
                )
            )
            .scalars()
            .all()
        )
        debate_power = {t: power[t] for t in debate_team_ids if t in power}
        if len(debate_power) < len(debate_team_ids) or len(debate_power) < 2:
            raise UnpriceableMarketError("not enough priced teams in this debate yet")
        a, b = team_ids
        if a not in debate_power or b not in debate_power:
            raise KeyError((a, b))
        temperature = adaptive_temperature(power.values())
        prior = pair_top_two_probability(debate_power, a, b, temperature=temperature)
        candidate_stake, debate_stake = await _debate_pair_pool(
            session, bet_market.id, debate_id, (a, b), exclude_user_id=exclude_user_id
        )
        return pari_mutuel_odds(candidate_stake, debate_stake, prior, seed=ELIMINATION_SEED)

    if bet_type == BetType.TOP_SPEAKER_POSITION:
        power = await compute_speaker_power_ratings(session, bet_market.tournament_id)
        if not power:
            raise UnpriceableMarketError("no speaker scores yet to price this market from")
        speaker_id = payload["speaker_id"]
        position = payload["position"]
        if position not in (1, 2, 3):
            raise ValueError("position must be 1, 2, or 3")
        if speaker_id not in power:
            raise KeyError(speaker_id)
        temperature = adaptive_temperature(power.values())
        probabilities = positional_probabilities(power, position, temperature=temperature)
        prior = probabilities[speaker_id]
        candidate_stake, compartment_stake = await _speaker_position_pool(
            session, bet_market.id, position, speaker_id, exclude_user_id=exclude_user_id
        )
        return pari_mutuel_odds(candidate_stake, compartment_stake, prior)

    if bet_type == BetType.TEAM_BREAK:
        # Independent, non-mutually-exclusive proposition ("does THIS team break", where
        # several teams break simultaneously) -- unlike every other bet type here, there's no
        # shared compartment to blend into: heavy betting on one team breaking says nothing
        # about any other team's chances, so this can't reuse e.g. CHAMPION's "stake on this
        # candidate out of the whole market's stake" pool. Each team instead gets blended
        # against its OWN money as its own one-candidate compartment (candidate_stake doubles as
        # compartment_stake) -- with no bets yet this is exactly the simulated probability, and
        # as real stake piles onto one team the price moves toward what the crowd is backing,
        # same "seed gets outweighed by real money" mechanic as every other market here (see
        # `app.domain.odds.pari_mutuel_probability`). This is what keeps two teams with similar
        # model probabilities from pricing wildly differently just because the crowd is much
        # more confident about one of them.
        if bet_market.target_break_category_id is None:
            raise UnpriceableMarketError("this market has no break category configured")
        probabilities = await team_break_probability(
            session, bet_market.tournament_id, bet_market.target_break_category_id
        )
        if not probabilities:
            raise UnpriceableMarketError("no teams registered in this break category yet")
        team_id = payload["team_id"]
        if team_id not in probabilities:
            raise KeyError(team_id)
        candidate_stake, _total = await _field_pool(
            session, bet_market.id, "team_id", team_id, exclude_user_id=exclude_user_id
        )
        return pari_mutuel_odds(candidate_stake, candidate_stake, probabilities[team_id])

    if bet_type == BetType.BEST_INSTITUTION:
        institution_power = await compute_institution_power_ratings(
            session, bet_market.tournament_id
        )
        if not institution_power:
            raise UnpriceableMarketError("no standings yet to price this market from")
        institution_code = payload["institution_code"]
        prior = softmax_probabilities(
            institution_power, temperature=adaptive_temperature(institution_power.values())
        )[institution_code]
        candidate_stake, market_stake = await _field_pool(
            session,
            bet_market.id,
            "institution_code",
            institution_code,
            exclude_user_id=exclude_user_id,
        )
        return pari_mutuel_odds(candidate_stake, market_stake, prior)

    if bet_type == BetType.TOP_N_BREAK:
        power = await compute_team_power_ratings(
            session, bet_market.tournament_id, break_category_id=bet_market.target_break_category_id
        )
        if not power:
            raise UnpriceableMarketError("no standings yet to price this market from")
        team_ids = list(payload["team_ids"])
        prior = sequence_probability(power, team_ids)
        candidate_stake, market_stake = await _sequence_pool(
            session, bet_market.id, "team_ids", team_ids, exclude_user_id=exclude_user_id
        )
        return pari_mutuel_odds(candidate_stake, market_stake, prior)

    if bet_type == BetType.TOP_N_SPEAKERS:
        power = await compute_speaker_power_ratings(session, bet_market.tournament_id)
        if not power:
            raise UnpriceableMarketError("no speaker scores yet to price this market from")
        speaker_ids = list(payload["speaker_ids"])
        prior = sequence_probability(power, speaker_ids)
        candidate_stake, market_stake = await _sequence_pool(
            session, bet_market.id, "speaker_ids", speaker_ids, exclude_user_id=exclude_user_id
        )
        return pari_mutuel_odds(candidate_stake, market_stake, prior)

    raise ValueError(f"no odds pricing implemented for bet type {bet_type!r}")


async def quote_sub_bet_odds(
    session: AsyncSession, bet_market: BetMarket, payload: dict
) -> float | None:
    """Prices the OPTIONAL modifier in `payload["sub_bet"]`, if present -- see
    `app.models.betting.Prediction`'s sub_bet_* column docstring for the "same bet slip, extra
    modifier" design. Returns `None` if no sub-bet was attempted (no "sub_bet" key in `payload`)
    or this bet_type has no modifier support at all.

    Deliberately NO pari-mutuel pool blending here (unlike `quote_odds`'s base pricing): these
    modifiers see far fewer bets than the base pick, so a seeded pool would rarely move off the
    prior anyway -- this stays a plain fair-book price straight from the model. Raises the same
    `UnpriceableMarketError`/`KeyError`/`ValueError` `quote_odds` does for equivalent situations.
    """
    sub_bet = payload.get("sub_bet")
    if not sub_bet:
        return None
    bet_type = bet_market.bet_type

    if bet_type == BetType.ROUND_HEAD_TO_HEAD:
        gap = sub_bet.get("rank_gap")
        if gap is None:
            raise ValueError("sub_bet.rank_gap is required")
        debate_id = payload["debate_id"]
        team_a_id, team_b_id = payload["team_a_id"], payload["team_b_id"]
        predicted_higher_id = payload["predicted_higher_id"]
        lower_id = team_b_id if predicted_higher_id == team_a_id else team_a_id
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        debate_team_ids = (
            (
                await session.execute(
                    select(DebateTeam.team_id).where(DebateTeam.debate_id == debate_id)
                )
            )
            .scalars()
            .all()
        )
        debate_power = {t: power[t] for t in debate_team_ids if t in power}
        if len(debate_power) < len(debate_team_ids) or len(debate_power) < 2:
            raise UnpriceableMarketError("not enough priced teams in this debate yet")
        temperature = adaptive_temperature(power.values())
        probability = exact_rank_gap_probability(
            debate_power, predicted_higher_id, lower_id, gap, temperature=temperature
        )
        return decimal_odds_from_probability(probability)

    if bet_type == BetType.TEAM_BREAK:
        if bet_market.target_break_category_id is None:
            raise UnpriceableMarketError("this market has no break category configured")
        exact_rank = sub_bet.get("exact_rank")
        if exact_rank is None:
            raise ValueError("sub_bet.exact_rank is required")
        team_id = payload["team_id"]
        rank_distribution = await team_break_exact_rank_probability(
            session, bet_market.tournament_id, bet_market.target_break_category_id, team_id
        )
        if not rank_distribution:
            raise UnpriceableMarketError(
                "not enough rounds judged yet to price the exact-rank sub-bet"
            )
        # A rank this team was never once simulated to land on prices as a genuine longshot
        # (near-zero probability -> MAX_ODDS via decimal_odds_from_probability), not an error --
        # 2000 simulated draws just not happening to hit it once is meaningfully different from
        # it being literally impossible.
        rank_odds = decimal_odds_from_probability(rank_distribution.get(exact_rank, 0.0))
        # "exact_points" has no principled probability model (see
        # DEFAULT_EXACT_POINTS_SUB_BET_ODDS) -- layers on as a flat multiplier on top of the
        # rank price rather than replacing it, since both conditions must hold together.
        if "exact_points" in sub_bet:
            return round(rank_odds * DEFAULT_EXACT_POINTS_SUB_BET_ODDS, 2)
        return rank_odds

    if bet_type == BetType.ROUND_WINNER:
        # Deferred family (see betting_service.settle_pending_sub_bets) -- no pool blending and
        # no per-payload probability model at all, just like DEFAULT_EXACT_POINTS_SUB_BET_ODDS
        # above; the shape is still validated here so a malformed sub_bet fails fast at quote
        # time rather than silently pricing as "no sub-bet" and surprising the user later.
        speaker_scores = sub_bet.get("speaker_scores")
        if not speaker_scores or len(speaker_scores) != 2:
            raise ValueError("sub_bet.speaker_scores must list exactly the team's 2 speakers")
        for entry in speaker_scores:
            if entry.get("speaker_id") is None or entry.get("points") is None:
                raise ValueError("sub_bet.speaker_scores entries need speaker_id and points")
        return DEFAULT_SPEAKER_POINTS_SUB_BET_ODDS

    return None


# --- Live market board -------------------------------------------------------------------
#
# Read-only aggregate for the "Mercados abiertos" UI: per candidate/option, how much is
# staked, by how many people, and what the CURRENT quoted odds are -- same math as
# `quote_odds` (seeded pari-mutuel), just computed for the whole field at once instead of a
# single payload, so a champion market over 60 teams doesn't cost 60 standings queries.


@dataclass(frozen=True)
class MarketBoardOption:
    key: str
    label: str
    emoji: str | None
    stake: float
    backers: int
    odds: float


@dataclass(frozen=True)
class MarketBoard:
    pool_total: float
    bettors: int
    options: list[MarketBoardOption]


_BOARD_MAX_UNSTAKED_OPTIONS = 12

_POSITION_LABELS = {1: "1º", 2: "2º", 3: "3º"}


def format_payload_label(
    bet_type: BetType,
    payload: dict,
    *,
    team_names: dict[int, tuple[str, str | None]],
    speaker_names: dict[int, str],
) -> tuple[str, str | None]:
    """Human-readable (label, emoji) for a prediction's payload, given already-fetched
    tournament-wide team/speaker name maps (no DB access here -- purely string formatting, so
    it's cheap to call once per prediction). Shared by `market_board`'s per-payload option rows
    and the user's bet-history endpoint (`GET /auth/me/predictions`, see
    `app.api.routers.auth.my_predictions`), so the two surfaces never drift out of sync."""

    def team(tid: object) -> tuple[str, str | None]:
        return team_names.get(tid, (f"Equipo {tid}", None))  # type: ignore[arg-type]

    if bet_type in (BetType.CHAMPION, BetType.BREAKOUT_TEAM):
        return team(payload.get("team_id"))
    if bet_type == BetType.TEAM_BREAK:
        name, emoji = team(payload.get("team_id"))
        sub_bet = payload.get("sub_bet") or {}
        if "exact_rank" in sub_bet and "exact_points" in sub_bet:
            return (
                f"{name} rompe #{sub_bet['exact_rank']} con {sub_bet['exact_points']} pts",
                emoji,
            )
        if "exact_rank" in sub_bet:
            return f"{name} rompe exactamente #{sub_bet['exact_rank']}", emoji
        return f"{name} rompe", emoji
    if bet_type == BetType.BEST_INSTITUTION:
        return payload.get("institution_code") or "—", None
    if bet_type == BetType.HEAD_TO_HEAD:
        winner, emoji = team(payload.get("predicted_winner_id"))
        a, _ = team(payload.get("team_a_id"))
        b, _ = team(payload.get("team_b_id"))
        return f"{winner} gana ({a} vs. {b})", emoji
    if bet_type == BetType.ROUND_WINNER:
        name, emoji = team(payload.get("team_id"))
        sub_bet = payload.get("sub_bet") or {}
        entries = sub_bet.get("speaker_scores") or []
        if entries:
            points = " y ".join(
                str(e["points"])
                for e in entries
                if e.get("points") is not None
            )
            return f"{name} gana su debate + oradores hacen {points} pts", emoji
        return f"{name} gana su debate", emoji
    if bet_type in (BetType.TOP_N_BREAK, BetType.ROUND_FULL_CALL):
        names = " → ".join(team(tid)[0] for tid in payload.get("team_ids", []))
        return names or "—", None
    if bet_type == BetType.TOP_N_SPEAKERS:
        names = " → ".join(
            speaker_names.get(sid, f"Speaker {sid}") for sid in payload.get("speaker_ids", [])
        )
        return names or "—", None
    if bet_type == BetType.TOP_SPEAKER_POSITION:
        speaker_id = payload.get("speaker_id")
        name = speaker_names.get(speaker_id, f"Speaker {speaker_id}")
        position_label = _POSITION_LABELS.get(payload.get("position"), "—")
        return f"{name} — {position_label}", None
    if bet_type == BetType.ROUND_HEAD_TO_HEAD:
        higher, emoji = team(payload.get("predicted_higher_id"))
        a, _ = team(payload.get("team_a_id"))
        b, _ = team(payload.get("team_b_id"))
        sub_bet = payload.get("sub_bet") or {}
        gap_suffix = f" por {sub_bet['rank_gap']} puesto(s)" if "rank_gap" in sub_bet else ""
        return f"{higher} arriba{gap_suffix} ({a} vs. {b})", emoji
    if bet_type == BetType.ROUND_ADVANCING_PAIR:
        names = " y ".join(team(tid)[0] for tid in payload.get("team_ids", []))
        return f"Avanzan {names}" if names else "—", None
    return "|".join(f"{k}={payload[k]}" for k in sorted(payload)) or "—", None


async def _generic_fallback_options(
    session: AsyncSession, bet_market: BetMarket, payload_by_key: dict[str, dict]
) -> dict[str, float]:
    """Prices every distinct payload for the bet types `market_board` has no dedicated
    enumerable-candidate branch for (round_winner, round_full_call, round_head_to_head,
    top_speaker_position, head_to_head, top_n_break, top_n_speakers, breakout_team). Returns
    {key: odds}, omitting any
    payload that can't be priced (mirrors `quote_odds` raising UnpriceableMarketError/KeyError/
    ValueError for that same payload, which callers used to `continue` past).

    Fetches power ratings and open stakes ONCE for the whole market, rather than calling
    `quote_odds` once per distinct payload -- which used to redo both from scratch every time
    (recomputing team/speaker power ratings from the full tournament's debate history, and
    re-scanning every open prediction on the market) for EACH of a round-scoped market's
    debates. A market with 10 debates x ~3 backed teams each meant ~30 full recomputations on
    every `/bets` page load; this does exactly one.

    The pricing math mirrors `quote_odds` exactly (same `_x_pool_from_stakes` helpers, same
    prior-probability calls with the same temperature) -- it MUST be kept in sync if either
    changes. `test_market_board_round_winner_multi_debate_characterization` pins the current
    output specifically to catch that drift.
    """
    bet_type = bet_market.bet_type

    if bet_type == BetType.BREAKOUT_TEAM:
        # No pool blending at all for this one (see quote_odds's matching branch) -- every
        # payload gets the same flat, admin-tunable price.
        flat_odds = float((bet_market.points_rule or {}).get("odds", DEFAULT_BREAKOUT_TEAM_ODDS))
        return dict.fromkeys(payload_by_key, flat_odds)

    if bet_type in (
        BetType.HEAD_TO_HEAD,
        BetType.ROUND_WINNER,
        BetType.ROUND_FULL_CALL,
        BetType.ROUND_HEAD_TO_HEAD,
        BetType.ROUND_ADVANCING_PAIR,
        BetType.TOP_N_BREAK,
    ):
        power = await compute_team_power_ratings(
            session,
            bet_market.tournament_id,
            break_category_id=(
                bet_market.target_break_category_id if bet_type == BetType.TOP_N_BREAK else None
            ),
        )
    elif bet_type in (BetType.TOP_SPEAKER_POSITION, BetType.TOP_N_SPEAKERS):
        power = await compute_speaker_power_ratings(session, bet_market.tournament_id)
    else:
        return {}

    if not power:
        return {}
    temperature = adaptive_temperature(power.values())
    open_stakes = await _open_stakes(session, bet_market.id)

    # Batch-fetch debate -> (round_id, [team_id, ...]) once for every distinct debate these
    # payloads reference, instead of the 2 queries per payload `quote_odds` would otherwise run
    # (one for _require_debate_in_round, one for the debate's team list).
    debate_ids = {
        payload["debate_id"]
        for payload in payload_by_key.values()
        if bet_type
        in (
            BetType.ROUND_WINNER,
            BetType.ROUND_FULL_CALL,
            BetType.ROUND_HEAD_TO_HEAD,
            BetType.ROUND_ADVANCING_PAIR,
        )
        and payload.get("debate_id") is not None
    }
    teams_by_debate: dict[int, list[int]] = defaultdict(list)
    round_by_debate: dict[int, int | None] = {}
    # Elimination rounds price as top-N ("does this team advance") rather than one-winner -- see
    # `_round_winner_odds`. Both facts it needs (the round's stage, and how many debates the
    # round has) are batch-fetched here for every round these payloads touch, so the board keeps
    # its "one query set for the whole market" property instead of calling `_advancing_count`
    # per debate.
    advancing_by_round: dict[int, int | None] = {}
    if debate_ids:
        debate_rows = (
            await session.execute(
                select(DebateTeam.debate_id, DebateTeam.team_id).where(
                    DebateTeam.debate_id.in_(debate_ids)
                )
            )
        ).all()
        for debate_id, team_id in debate_rows:
            teams_by_debate[debate_id].append(team_id)
        round_rows = (
            await session.execute(
                select(Debate.id, Debate.round_id).where(Debate.id.in_(debate_ids))
            )
        ).all()
        round_by_debate = dict(round_rows)
        round_ids = {rid for rid in round_by_debate.values() if rid is not None}
        if round_ids:
            stage_rows = (
                await session.execute(
                    select(Round.id, Round.stage, func.count(Debate.id))
                    .join(Debate, Debate.round_id == Round.id)
                    .where(Round.id.in_(round_ids))
                    .group_by(Round.id, Round.stage)
                )
            ).all()
            for round_id, stage, debate_count in stage_rows:
                advancing_by_round[round_id] = (
                    None
                    if stage != RoundStage.ELIMINATION
                    else (1 if debate_count <= 1 else 2)
                )

    odds_by_key: dict[str, float] = {}
    for key, payload in payload_by_key.items():
        try:
            if bet_type == BetType.HEAD_TO_HEAD:
                team_a_id, team_b_id = payload["team_a_id"], payload["team_b_id"]
                pair_power = {t: power[t] for t in (team_a_id, team_b_id) if t in power}
                if len(pair_power) != 2:
                    continue
                predicted_winner_id = payload["predicted_winner_id"]
                prior = softmax_probabilities(pair_power, temperature=temperature)[
                    predicted_winner_id
                ]
                candidate_stake, compartment_stake = _pair_pool_from_stakes(
                    open_stakes, team_a_id, team_b_id, predicted_winner_id
                )

            elif bet_type == BetType.ROUND_WINNER:
                debate_id = payload["debate_id"]
                if (
                    bet_market.target_round_id is not None
                    and round_by_debate.get(debate_id) != bet_market.target_round_id
                ):
                    continue
                debate_power = {
                    t: power[t] for t in teams_by_debate.get(debate_id, []) if t in power
                }
                if len(debate_power) < 2:
                    continue
                team_id = payload["team_id"]
                candidate_stake, compartment_stake = _debate_pool_from_stakes(
                    open_stakes, debate_id, team_id
                )
                odds_by_key[key] = _round_winner_odds(
                    debate_power,
                    team_id,
                    temperature=temperature,
                    candidate_stake=candidate_stake,
                    compartment_stake=compartment_stake,
                    advancing_count=advancing_by_round.get(round_by_debate.get(debate_id)),
                )
                continue

            elif bet_type == BetType.ROUND_FULL_CALL:
                debate_id = payload["debate_id"]
                if (
                    bet_market.target_round_id is not None
                    and round_by_debate.get(debate_id) != bet_market.target_round_id
                ):
                    continue
                debate_team_ids = teams_by_debate.get(debate_id, [])
                debate_power = {t: power[t] for t in debate_team_ids if t in power}
                if len(debate_power) < len(debate_team_ids) or len(debate_power) < 2:
                    continue
                team_ids = list(payload["team_ids"])
                if set(team_ids) != set(debate_team_ids):
                    continue
                prior = sequence_probability(debate_power, team_ids, temperature=temperature)
                candidate_stake, compartment_stake = _debate_sequence_pool_from_stakes(
                    open_stakes, debate_id, team_ids
                )

            elif bet_type == BetType.ROUND_HEAD_TO_HEAD:
                debate_id = payload["debate_id"]
                if (
                    bet_market.target_round_id is not None
                    and round_by_debate.get(debate_id) != bet_market.target_round_id
                ):
                    continue
                team_a_id, team_b_id = payload["team_a_id"], payload["team_b_id"]
                pair_power = {t: power[t] for t in (team_a_id, team_b_id) if t in power}
                if len(pair_power) != 2:
                    continue
                predicted_higher_id = payload["predicted_higher_id"]
                if predicted_higher_id not in (team_a_id, team_b_id):
                    continue
                prior = softmax_probabilities(pair_power, temperature=temperature)[
                    predicted_higher_id
                ]
                candidate_stake, compartment_stake = _pair_pool_from_stakes(
                    open_stakes,
                    team_a_id,
                    team_b_id,
                    predicted_higher_id,
                    predicted_field="predicted_higher_id",
                    debate_id=debate_id,
                )

            elif bet_type == BetType.ROUND_ADVANCING_PAIR:
                debate_id = payload["debate_id"]
                if (
                    bet_market.target_round_id is not None
                    and round_by_debate.get(debate_id) != bet_market.target_round_id
                ):
                    continue
                if advancing_by_round.get(round_by_debate.get(debate_id)) != 2:
                    continue
                team_ids = payload.get("team_ids")
                if not team_ids or len(team_ids) != 2:
                    continue
                a, b = team_ids
                debate_team_ids = teams_by_debate.get(debate_id, [])
                debate_power = {t: power[t] for t in debate_team_ids if t in power}
                if (
                    len(debate_power) < len(debate_team_ids)
                    or a not in debate_power
                    or b not in debate_power
                ):
                    continue
                prior = pair_top_two_probability(debate_power, a, b, temperature=temperature)
                candidate_stake, compartment_stake = _debate_pair_pool_from_stakes(
                    open_stakes, debate_id, (a, b)
                )
                odds_by_key[key] = pari_mutuel_odds(
                    candidate_stake, compartment_stake, prior, seed=ELIMINATION_SEED
                )
                continue

            elif bet_type == BetType.TOP_SPEAKER_POSITION:
                speaker_id = payload["speaker_id"]
                position = payload["position"]
                if position not in (1, 2, 3) or speaker_id not in power:
                    continue
                probabilities = positional_probabilities(power, position, temperature=temperature)
                prior = probabilities[speaker_id]
                candidate_stake, compartment_stake = _speaker_position_pool_from_stakes(
                    open_stakes, position, speaker_id
                )

            elif bet_type == BetType.TOP_N_BREAK:
                team_ids = list(payload["team_ids"])
                prior = sequence_probability(power, team_ids, temperature=temperature)
                candidate_stake, compartment_stake = _sequence_pool_from_stakes(
                    open_stakes, "team_ids", team_ids
                )

            else:  # TOP_N_SPEAKERS
                speaker_ids = list(payload["speaker_ids"])
                prior = sequence_probability(power, speaker_ids, temperature=temperature)
                candidate_stake, compartment_stake = _sequence_pool_from_stakes(
                    open_stakes, "speaker_ids", speaker_ids
                )
        except (KeyError, ValueError):
            continue

        odds_by_key[key] = pari_mutuel_odds(candidate_stake, compartment_stake, prior)

    return odds_by_key


async def market_board(session: AsyncSession, bet_market: BetMarket) -> MarketBoard:
    rows = (
        await session.execute(
            select(Prediction.user_id, Prediction.payload, Prediction.stake_amount).where(
                Prediction.bet_market_id == bet_market.id
            )
        )
    ).all()
    pool_total = sum(float(stake) for _, _, stake in rows)
    bettors = len({user_id for user_id, _, _ in rows})

    bet_type = bet_market.bet_type
    options: list[MarketBoardOption] = []

    def _stakes_by(key_fn) -> tuple[dict, dict]:
        stake_by: dict = defaultdict(float)
        backers_by: dict = defaultdict(set)
        for (user_id, payload, stake) in rows:
            key = key_fn(payload)
            if key is None:
                continue
            stake_by[key] += float(stake)
            backers_by[key].add(user_id)
        return stake_by, {k: len(v) for k, v in backers_by.items()}

    if bet_type == BetType.CHAMPION:
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        if not power:
            return MarketBoard(pool_total=pool_total, bettors=bettors, options=[])
        probs = softmax_probabilities(power, temperature=adaptive_temperature(power.values()))
        stake_by, backers_by = _stakes_by(lambda p: p.get("team_id"))
        total_open = sum(stake_by.values())
        teams = {
            t.id: t
            for t in (
                await session.execute(
                    select(Team).where(Team.tournament_id == bet_market.tournament_id)
                )
            ).scalars()
        }
        ranked = sorted(probs, key=lambda tid: -probs[tid])
        keep = [tid for tid in ranked if stake_by.get(tid)] + [
            tid for tid in ranked if not stake_by.get(tid)
        ][:_BOARD_MAX_UNSTAKED_OPTIONS]
        for tid in sorted(set(keep), key=lambda t: -probs.get(t, 0.0)):
            team = teams.get(tid)
            if team is None:
                continue
            options.append(
                MarketBoardOption(
                    key=f"team:{tid}",
                    label=team.name,
                    emoji=team.emoji,
                    stake=round(stake_by.get(tid, 0.0), 2),
                    backers=backers_by.get(tid, 0),
                    odds=pari_mutuel_odds(stake_by.get(tid, 0.0), total_open, probs[tid]),
                )
            )
        return MarketBoard(pool_total=pool_total, bettors=bettors, options=options)

    if bet_type == BetType.BEST_INSTITUTION:
        institution_power = await compute_institution_power_ratings(
            session, bet_market.tournament_id
        )
        if not institution_power:
            return MarketBoard(pool_total=pool_total, bettors=bettors, options=[])
        probs = softmax_probabilities(
            institution_power, temperature=adaptive_temperature(institution_power.values())
        )
        stake_by, backers_by = _stakes_by(lambda p: p.get("institution_code"))
        total_open = sum(stake_by.values())
        for code in sorted(probs, key=lambda c: -probs[c]):
            options.append(
                MarketBoardOption(
                    key=f"inst:{code}",
                    label=code,
                    emoji=None,
                    stake=round(stake_by.get(code, 0.0), 2),
                    backers=backers_by.get(code, 0),
                    odds=pari_mutuel_odds(stake_by.get(code, 0.0), total_open, probs[code]),
                )
            )
        return MarketBoard(pool_total=pool_total, bettors=bettors, options=options[:20])

    if bet_type == BetType.TEAM_BREAK:
        if bet_market.target_break_category_id is None:
            return MarketBoard(pool_total=pool_total, bettors=bettors, options=[])
        probabilities = await team_break_probability(
            session, bet_market.tournament_id, bet_market.target_break_category_id
        )
        if not probabilities:
            return MarketBoard(pool_total=pool_total, bettors=bettors, options=[])
        stake_by, backers_by = _stakes_by(lambda p: p.get("team_id"))
        teams = {
            t.id: t
            for t in (
                await session.execute(select(Team).where(Team.id.in_(probabilities.keys())))
            ).scalars()
        }
        for tid in sorted(probabilities, key=lambda t: -probabilities[t]):
            team = teams.get(tid)
            if team is None:
                continue
            team_stake = stake_by.get(tid, 0.0)
            options.append(
                MarketBoardOption(
                    key=f"team:{tid}",
                    label=team.name,
                    emoji=team.emoji,
                    stake=round(team_stake, 2),
                    backers=backers_by.get(tid, 0),
                    # Own-money-as-own-compartment blend -- see the matching comment in
                    # quote_odds's TEAM_BREAK branch.
                    odds=pari_mutuel_odds(team_stake, team_stake, probabilities[tid]),
                )
            )
        return MarketBoard(pool_total=pool_total, bettors=bettors, options=options)

    # Remaining bet types have no enumerable candidate field (their options are whatever
    # payload combinations people actually staked), so the board lists the staked picks and
    # prices each one -- see `_generic_fallback_options` for how this avoids re-fetching power
    # ratings and stakes once per distinct payload the way calling `quote_odds` in a loop would.
    def _payload_key(payload: dict) -> str:
        return "|".join(f"{k}={payload[k]}" for k in sorted(payload))

    stake_by, backers_by = _stakes_by(_payload_key)
    payload_by_key = {}
    for _, payload, _stake in rows:
        payload_by_key[_payload_key(payload)] = payload

    team_names = {
        t.id: (t.name, t.emoji)
        for t in (
            await session.execute(
                select(Team).where(Team.tournament_id == bet_market.tournament_id)
            )
        ).scalars()
    }
    speaker_names = {
        s.id: s.name
        for s in (
            await session.execute(
                select(Speaker).where(Speaker.tournament_id == bet_market.tournament_id)
            )
        ).scalars()
    }

    odds_by_key = await _generic_fallback_options(session, bet_market, payload_by_key)

    for key, payload in payload_by_key.items():
        odds = odds_by_key.get(key)
        if odds is None:
            continue
        label, emoji = format_payload_label(
            bet_type, payload, team_names=team_names, speaker_names=speaker_names
        )
        options.append(
            MarketBoardOption(
                key=key,
                label=label,
                emoji=emoji,
                stake=round(stake_by.get(key, 0.0), 2),
                backers=backers_by.get(key, 0),
                odds=odds,
            )
        )
    options.sort(key=lambda o: -o.stake)
    return MarketBoard(pool_total=pool_total, bettors=bettors, options=options)
