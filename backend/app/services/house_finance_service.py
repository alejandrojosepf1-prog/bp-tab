"""Derived "house" accounting for the admin panel's Finanzas de la Casa view.

There's no literal money or bankroll held anywhere in this app -- see `app.domain.odds`'s
module docstring: a winning prediction is paid by crediting `User.balance` directly, a losing
one just has its stake deducted, with no pooled fund backing either side. Everything here is a
VIEW computed from existing `Prediction` rows, not a new ledger: what's been collected, what's
already been paid out (both facts, from SETTLED predictions), and -- for markets still OPEN -- a
projection of what the house's cash flow WOULD be under each plausible outcome.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BetMarket, Prediction
from app.models.enums import BetType, PredictionStatus


@dataclass(frozen=True)
class HouseSummary:
    total_staked_open: float
    total_staked_settled: float
    total_paid_out: float
    # total_staked_settled - total_paid_out: only counts fully-resolved predictions, since an
    # OPEN prediction's stake is still a liability, not realized house revenue.
    realized_net_profit: float


@dataclass(frozen=True)
class MarketExposure:
    market_id: int
    market_label: str
    pool_total: float
    # Most negative (largest house loss) and most positive (largest house gain) plausible
    # cash-flow scenario across this market's currently-OPEN predictions. See
    # `compute_market_exposure` for exactly what "plausible" means per bet_type.
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


async def compute_market_exposure(
    session: AsyncSession, market: BetMarket
) -> MarketExposure | None:
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
        # actually breaking (house pays every open prediction its full stake*odds); best case is
        # NONE of them breaking (house keeps the whole pool). Doesn't group by outcome, since
        # there's no single mutually-exclusive "the" outcome here.
        total_liability = sum(float(stake) * float(odds) for _, stake, odds in rows)
        return MarketExposure(
            market_id=market.id,
            market_label=market.label,
            pool_total=pool,
            worst_case=pool - total_liability,
            best_case=pool,
        )

    # Mutually-exclusive-outcome markets: for each distinct outcome actually backed by an open
    # prediction, plus the baseline "house keeps everything" scenario (the real outcome matches
    # none of them), compute the house's net cash flow if THAT outcome occurs, then take the
    # min/max across those scenarios. This is a proxy over the outcomes people actually bet on,
    # not an exhaustive enumeration of the whole candidate field (e.g. a champion market's
    # untouched longshots aren't each their own scenario) -- deliberately so, since only a
    # backed outcome can change the house's liability at all.
    liability_by_outcome: dict[str, float] = {}
    for payload, stake, odds in rows:
        key = _outcome_key(market.bet_type, payload)
        if key is None:
            continue
        liability_by_outcome[key] = liability_by_outcome.get(key, 0.0) + float(stake) * float(odds)

    scenarios = [pool - liability for liability in liability_by_outcome.values()]
    scenarios.append(pool)  # nobody who has an open bet turns out to be right
    return MarketExposure(
        market_id=market.id,
        market_label=market.label,
        pool_total=pool,
        worst_case=min(scenarios),
        best_case=max(scenarios),
    )


async def compute_house_summary(
    session: AsyncSession, tournament_id: int | None = None
) -> HouseSummary:
    stmt = select(Prediction.status, Prediction.stake_amount, Prediction.points_awarded)
    if tournament_id is not None:
        stmt = stmt.join(BetMarket, Prediction.bet_market_id == BetMarket.id).where(
            BetMarket.tournament_id == tournament_id
        )
    rows = (await session.execute(stmt)).all()

    total_staked_open = sum(
        float(stake) for status, stake, _ in rows if status != PredictionStatus.SETTLED
    )
    total_staked_settled = sum(
        float(stake) for status, stake, _ in rows if status == PredictionStatus.SETTLED
    )
    total_paid_out = sum(
        float(points or 0.0) for status, _, points in rows if status == PredictionStatus.SETTLED
    )
    return HouseSummary(
        total_staked_open=total_staked_open,
        total_staked_settled=total_staked_settled,
        total_paid_out=total_paid_out,
        realized_net_profit=total_staked_settled - total_paid_out,
    )
