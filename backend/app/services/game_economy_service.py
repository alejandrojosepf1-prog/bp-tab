"""Derived economy accounting for the admin panel's "Actividad y economía del juego" view.

Claim has no house: no operator, no bankroll, no commission (see app.domain.odds's module
docstring). So nothing here is framed as "the house's" profit or risk -- everything is a VIEW
computed from existing `Prediction`/`User` rows, describing the token economy as a whole: how
many tokens exist, how many are committed to open bets, and -- the metric that actually matters
without a house backing payouts -- whether the economy is net INFLATING. Odds are locked at bet
time and paid at `stake * odds` regardless of pool size (see
app.services.betting_service.settle_market), so whenever favorites win, payouts exceed what was
staked on them and the platform mints tokens; whenever longshots win, tokens are net destroyed.
`net_token_inflation` is exactly that gap, summed across every settled prediction.

`compute_market_payout_spread` (per-market worst/best-case payout projection) is unrelated to
inflation -- it answers "how would this market's payouts vary depending on how it resolves,"
useful for an admin gut-checking whether a market's pricing looks reasonable before it settles.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BetMarket, Prediction, TournamentBalance
from app.models.enums import BetType, PredictionStatus


@dataclass(frozen=True)
class EconomySummary:
    total_staked_open: float
    total_staked_settled: float
    total_paid_out: float
    # total_paid_out - total_staked_settled, summed across every SETTLED prediction. Positive
    # means the platform has net MINTED tokens (favorites won more often/heavily than their odds
    # implied); negative means tokens were net destroyed. Zero only by coincidence -- there is no
    # mechanism that forces this to balance, unlike a real pari-mutuel pool.
    net_token_inflation: float
    # Sum of every TournamentBalance.balance in scope -- the total token supply live in the game
    # right now, including tokens still committed to open predictions (a user's stake is
    # deducted from balance the moment they bet, so it's "spent" from their wallet but not yet
    # destroyed or paid out).
    tokens_in_circulation: float
    open_predictions_count: int
    settled_predictions_count: int
    # Distinct users with at least one prediction (open or settled) anywhere in scope.
    active_bettors_count: int


@dataclass(frozen=True)
class MarketPayoutSpread:
    market_id: int
    market_label: str
    pool_total: float
    # Most negative (largest net token destruction) and most positive (largest net token
    # creation) plausible payout scenario across this market's currently-OPEN predictions. See
    # `compute_market_payout_spread` for exactly what "plausible" means per bet_type. Framed as
    # "pool minus what would be paid out," NOT house profit/loss -- there is no house.
    worst_case: float
    best_case: float


def _outcome_key(bet_type: BetType, payload: dict) -> str | None:
    """Groups OPEN predictions on a market by the specific real-world outcome that would make
    them win. Finer-grained than `Prediction.entity_key` (which only dedupes one USER's bets --
    e.g. entity_key groups by debate alone for round_winner, but two different users backing
    DIFFERENT teams in that same debate must be split here, since only one of them can win).
    Returns None (excluded from the projection) for a payload missing the fields this bet_type
    needs -- a malformed/legacy row must never crash the whole projection.
    """
    try:
        if bet_type in (BetType.CHAMPION, BetType.BREAKOUT_TEAM):
            return f"team:{payload['team_id']}"
        if bet_type == BetType.BEST_INSTITUTION:
            return f"inst:{payload['institution_code']}"
        if bet_type == BetType.ROUND_WINNER:
            return f"debate:{payload['debate_id']}:team:{payload['team_id']}"
        if bet_type == BetType.ROUND_FULL_CALL:
            order = ",".join(str(t) for t in payload["team_ids"])
            return f"debate:{payload['debate_id']}:order:{order}"
        if bet_type == BetType.TOP_SPEAKER_POSITION:
            return f"position:{payload['position']}:speaker:{payload['speaker_id']}"
        if bet_type == BetType.HEAD_TO_HEAD:
            a, b = sorted([payload["team_a_id"], payload["team_b_id"]])
            return f"pair:{a}:{b}:winner:{payload['predicted_winner_id']}"
        if bet_type in (BetType.TOP_N_BREAK, BetType.TOP_N_SPEAKERS):
            key = "team_ids" if bet_type == BetType.TOP_N_BREAK else "speaker_ids"
            return f"seq:{','.join(str(i) for i in payload[key])}"
    except (KeyError, TypeError):
        return None
    return None


async def compute_market_payout_spread(
    session: AsyncSession, market: BetMarket
) -> MarketPayoutSpread | None:
    """None if the market has no OPEN predictions at all (nothing to project)."""
    rows = (
        await session.execute(
            select(Prediction.payload, Prediction.stake_amount, Prediction.odds).where(
                Prediction.bet_market_id == market.id,
                Prediction.status != PredictionStatus.SETTLED,
            )
        )
    ).all()
    if not rows:
        return None
    pool = sum(float(stake) for _, stake, _ in rows)

    if market.bet_type == BetType.TEAM_BREAK:
        # Independent, non-mutually-exclusive propositions (several teams can break at once --
        # see the matching comment in odds_service.quote_odds): worst case is EVERY backed team
        # actually breaking (every open prediction paid its full stake*odds); best case is NONE
        # of them breaking (nothing paid out, pool tokens simply sit spent-but-unresolved).
        # Doesn't group by outcome, since there's no single mutually-exclusive "the" outcome here.
        total_liability = sum(float(stake) * float(odds) for _, stake, odds in rows)
        return MarketPayoutSpread(
            market_id=market.id,
            market_label=market.label,
            pool_total=pool,
            worst_case=pool - total_liability,
            best_case=pool,
        )

    # Mutually-exclusive-outcome markets: for each distinct outcome actually backed by an open
    # prediction, plus the baseline "nobody who bet turns out right" scenario, compute the net
    # payout if THAT outcome occurs, then take the min/max across those scenarios. This is a
    # proxy over the outcomes people actually bet on, not an exhaustive enumeration of the whole
    # candidate field (e.g. a champion market's untouched longshots aren't each their own
    # scenario) -- deliberately so, since only a backed outcome can change the payout at all.
    liability_by_outcome: dict[str, float] = {}
    for payload, stake, odds in rows:
        key = _outcome_key(market.bet_type, payload)
        if key is None:
            continue
        liability_by_outcome[key] = liability_by_outcome.get(key, 0.0) + float(stake) * float(odds)

    scenarios = [pool - liability for liability in liability_by_outcome.values()]
    scenarios.append(pool)  # nobody who has an open bet turns out to be right
    return MarketPayoutSpread(
        market_id=market.id,
        market_label=market.label,
        pool_total=pool,
        worst_case=min(scenarios),
        best_case=max(scenarios),
    )


async def compute_game_economy(
    session: AsyncSession, tournament_id: int | None = None
) -> EconomySummary:
    stmt = select(
        Prediction.status, Prediction.stake_amount, Prediction.points_awarded, Prediction.user_id
    )
    if tournament_id is not None:
        stmt = stmt.join(BetMarket, Prediction.bet_market_id == BetMarket.id).where(
            BetMarket.tournament_id == tournament_id
        )
    rows = (await session.execute(stmt)).all()

    total_staked_open = sum(
        float(stake) for status, stake, _, _ in rows if status != PredictionStatus.SETTLED
    )
    total_staked_settled = sum(
        float(stake) for status, stake, _, _ in rows if status == PredictionStatus.SETTLED
    )
    total_paid_out = sum(
        float(points or 0.0)
        for status, _, points, _ in rows
        if status == PredictionStatus.SETTLED
    )
    open_predictions_count = sum(
        1 for status, _, _, _ in rows if status != PredictionStatus.SETTLED
    )
    settled_predictions_count = sum(
        1 for status, _, _, _ in rows if status == PredictionStatus.SETTLED
    )
    active_bettors_count = len({user_id for _, _, _, user_id in rows})

    # Token supply now IS scoped by tournament_id when given (CNADE 2026 Roadmap Pieza 3 --
    # balance is per-tournament, see TournamentBalance), unlike before this when it was
    # deliberately the one platform-wide figure in an otherwise tournament-scoped summary.
    balance_stmt = select(func.coalesce(func.sum(TournamentBalance.balance), 0.0))
    if tournament_id is not None:
        balance_stmt = balance_stmt.where(TournamentBalance.tournament_id == tournament_id)
    tokens_in_circulation = float((await session.execute(balance_stmt)).scalar_one())

    return EconomySummary(
        total_staked_open=total_staked_open,
        total_staked_settled=total_staked_settled,
        total_paid_out=total_paid_out,
        net_token_inflation=total_paid_out - total_staked_settled,
        tokens_in_circulation=tokens_in_circulation,
        open_predictions_count=open_predictions_count,
        settled_predictions_count=settled_predictions_count,
        active_bettors_count=active_bettors_count,
    )
