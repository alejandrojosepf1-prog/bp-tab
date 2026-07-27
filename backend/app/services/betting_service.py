"""Settles a BetMarket: builds the real-world outcome, scores every Prediction against it,
and refreshes the tournament's leaderboard.

Most bet types have ONE outcome shared by every prediction on the market (who's champion,
who broke, who topped the speaker tab, ...) and are resolved by `build_market_outcome`.
A handful are inherently per-prediction because the user's own payload picks *which* debate
they're predicting on (``ROUND_WINNER``, ``ROUND_FULL_CALL``) or *which* pair of teams
(``HEAD_TO_HEAD``, retired) -- those go through `build_prediction_specific_outcome` instead,
once per prediction.

``BREAKOUT_TEAM`` (retired) has no mechanically derivable outcome at all -- it's a qualitative
admin judgment call about which team most exceeded expectations -- so it can only be settled by
passing `manual_outcome` explicitly (normally triggered from the admin panel).

This module also owns the creation-time rules for the five bet types the admin panel actually
offers (`CREATABLE_BET_TYPES`, `validate_market_creation`) and the one that auto-expires on its
own schedule rather than by admin action (`CHAMPION` -- see `auto_close_pretournament_markets`).
"""

import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bet_outcomes import did_prediction_win
from app.models import (
    Break,
    Debate,
    DebateTeam,
    Institution,
    LeaderboardEntry,
    Prediction,
    SpeakerScore,
    Team,
    Tournament,
    User,
)
from app.models.betting import BetMarket
from app.models.enums import BetMarketStatus, BetType, PredictionStatus, TournamentStatus
from app.repositories.upsert import upsert_by_natural_key
from app.services.odds_service import quote_odds
from app.services.ranking_service import get_standings

_PER_PREDICTION_BET_TYPES = {BetType.HEAD_TO_HEAD, BetType.ROUND_WINNER, BetType.ROUND_FULL_CALL}

# Bet types still creatable from the admin panel -- see app.models.enums.BetType for why
# top_n_break/top_n_speakers/head_to_head/breakout_team/best_institution are no longer here.
CREATABLE_BET_TYPES = (
    BetType.CHAMPION,
    BetType.ROUND_WINNER,
    BetType.ROUND_FULL_CALL,
    BetType.TOP_SPEAKER_POSITION,
    BetType.TEAM_BREAK,
)

_ROUND_SCOPED_BET_TYPES = {BetType.ROUND_WINNER, BetType.ROUND_FULL_CALL}


class InsufficientBalanceError(Exception):
    """Raised when a user's balance can't cover a stake -- the router maps this to a 400."""


class MarketCreationError(Exception):
    """Raised when a market can't be created against this tournament's/payload's current
    state -- the router maps this to a 400."""


def validate_market_creation(
    tournament: Tournament,
    bet_type: BetType,
    *,
    target_round_id: int | None,
    target_break_category_id: int | None,
) -> None:
    """Enforces the creation-time constraints for each of the five creatable bet types (see
    `CREATABLE_BET_TYPES`). Called before a BetMarket row is even constructed -- nothing here
    touches the database itself."""
    if bet_type not in CREATABLE_BET_TYPES:
        raise MarketCreationError(
            f"'{bet_type.value}' ya no se puede crear desde el panel de admin."
        )
    if bet_type == BetType.CHAMPION and tournament.status != TournamentStatus.UPCOMING:
        raise MarketCreationError(
            "El mercado de campeón solo se puede crear antes de que arranque el torneo."
        )
    if bet_type in _ROUND_SCOPED_BET_TYPES and target_round_id is None:
        raise MarketCreationError("Este tipo de mercado requiere elegir una ronda.")
    if bet_type == BetType.TEAM_BREAK and target_break_category_id is None:
        raise MarketCreationError("Este tipo de mercado requiere elegir una categoría de break.")


async def auto_close_pretournament_markets(session: AsyncSession, tournament: Tournament) -> int:
    """Once a tournament leaves UPCOMING (any preliminary result is in), any still-OPEN
    CHAMPION market for it must stop taking new bets -- "solo se puede apostar antes del
    torneo". Called every scrape cycle, right after `tournament_service.refresh_tournament_status`
    -- see `app.tasks.scrape_tasks`. Returns how many markets were closed (0 most cycles)."""
    if tournament.status == TournamentStatus.UPCOMING:
        return 0
    stmt = select(BetMarket).where(
        BetMarket.tournament_id == tournament.id,
        BetMarket.bet_type == BetType.CHAMPION,
        BetMarket.status == BetMarketStatus.OPEN,
    )
    markets = (await session.execute(stmt)).scalars().all()
    for market in markets:
        market.status = BetMarketStatus.CLOSED
    return len(markets)


def _entity_key(bet_type: BetType, payload: dict) -> str:
    """What a prediction competes against for uniqueness within (market, user) -- see
    `Prediction.entity_key`'s docstring. Single-choice bet types (you pick exactly one
    mutually-exclusive winner for the whole market) share one sentinel key, so a second bet
    still replaces the first exactly like before this concept existed. Bet types whose payload
    names a specific sub-entity (a debate, a top-3 slot, an independent team) get one key per
    distinct value of that field, so a user can hold one open prediction PER debate/slot/team
    instead of one per market.

    Raises KeyError if the payload is missing the field this bet_type keys on -- callers
    already validate payload shape via `quote_odds` before this runs, so that should never
    happen in practice; this is deliberately not more defensive than that.
    """
    if bet_type in (BetType.ROUND_WINNER, BetType.ROUND_FULL_CALL):
        return f"debate:{payload['debate_id']}"
    if bet_type == BetType.TOP_SPEAKER_POSITION:
        return f"position:{payload['position']}"
    if bet_type == BetType.TEAM_BREAK:
        return f"team:{payload['team_id']}"
    if bet_type == BetType.HEAD_TO_HEAD:
        a, b = sorted([payload["team_a_id"], payload["team_b_id"]])
        return f"pair:{a}:{b}"
    return "__market__"


async def place_prediction(
    session: AsyncSession,
    bet_market: BetMarket,
    user: User,
    payload: dict,
    stake_amount: float,
) -> Prediction:
    """Prices `payload` via `odds_service.quote_odds`, charges `stake_amount` against
    `user.balance`, and upserts the Prediction row with odds locked in at this moment.

    A user can hold one OPEN prediction per (market, entity_key) -- see `_entity_key` -- so
    betting on a different debate/slot/team within the same market creates a SEPARATE
    prediction rather than overwriting the last one; only re-submitting the SAME entity_key
    edits it. If the user already has an OPEN prediction for that entity_key (they're changing
    their pick before it closes), that prior stake is refunded first so editing a bet never
    double-charges them. Raises InsufficientBalanceError if the balance (after any refund)
    can't cover the new stake -- callers should not commit the session in that case.
    """
    if stake_amount <= 0:
        raise ValueError("stake_amount must be positive")

    odds = await quote_odds(session, bet_market, payload, exclude_user_id=user.id)
    entity_key = _entity_key(bet_market.bet_type, payload)

    existing = (
        await session.execute(
            select(Prediction).where(
                Prediction.bet_market_id == bet_market.id,
                Prediction.user_id == user.id,
                Prediction.entity_key == entity_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == PredictionStatus.OPEN:
        user.balance += existing.stake_amount

    if user.balance < stake_amount:
        raise InsufficientBalanceError(
            f"insufficient balance: have {user.balance:.2f}, need {stake_amount:.2f}"
        )
    user.balance -= stake_amount

    now = datetime.datetime.now(datetime.timezone.utc)
    result = await upsert_by_natural_key(
        session,
        Prediction,
        lookup={"bet_market_id": bet_market.id, "user_id": user.id, "entity_key": entity_key},
        values={
            "payload": payload,
            "locked_at": now,
            "status": PredictionStatus.OPEN,
            "stake_amount": stake_amount,
            "odds": odds,
            "points_awarded": None,
        },
    )
    return result.instance


async def build_market_outcome(session: AsyncSession, bet_market: BetMarket) -> dict | None:
    """Outcome shared by every prediction on this market, or None if not resolvable yet."""
    if bet_market.bet_type == BetType.CHAMPION:
        tournament = await session.get(Tournament, bet_market.tournament_id)
        if tournament is None or tournament.champion_team_id is None:
            return None
        return {"champion_team_id": tournament.champion_team_id}

    if bet_market.bet_type == BetType.TOP_N_BREAK:
        if bet_market.target_break_category_id is None:
            return None
        team_ids = (
            (
                await session.execute(
                    select(Break.team_id)
                    .where(
                        Break.tournament_id == bet_market.tournament_id,
                        Break.break_category_id == bet_market.target_break_category_id,
                    )
                    .order_by(Break.rank)
                )
            )
            .scalars()
            .all()
        )
        return {"breaking_team_ids": list(team_ids)} if team_ids else None

    if bet_market.bet_type == BetType.TOP_N_SPEAKERS:
        speaker_ids = await _get_final_speaker_ranking(session, bet_market.tournament_id)
        return {"top_speaker_ids": speaker_ids} if speaker_ids else None

    if bet_market.bet_type == BetType.BEST_INSTITUTION:
        standings = await get_standings(session, bet_market.tournament_id)
        if not standings:
            return None
        top_team = await session.get(Team, standings[0].team_id)
        if top_team is None or top_team.institution_id is None:
            return None
        institution = await session.get(Institution, top_team.institution_id)
        return {"institution_code": institution.code} if institution else None

    if bet_market.bet_type == BetType.TOP_SPEAKER_POSITION:
        speaker_ids = await _get_final_speaker_ranking(session, bet_market.tournament_id)
        if len(speaker_ids) < 3:
            return None
        return {"position_winners": {1: speaker_ids[0], 2: speaker_ids[1], 3: speaker_ids[2]}}

    if bet_market.bet_type == BetType.TEAM_BREAK:
        if bet_market.target_break_category_id is None:
            return None
        team_ids = (
            (
                await session.execute(
                    select(Break.team_id).where(
                        Break.tournament_id == bet_market.tournament_id,
                        Break.break_category_id == bet_market.target_break_category_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return {"breaking_team_ids": list(team_ids)} if team_ids else None

    return (
        None  # BREAKOUT_TEAM needs a manual outcome; HEAD_TO_HEAD/ROUND_WINNER/ROUND_FULL_CALL
        # are per-prediction (see build_prediction_specific_outcome)
    )


async def build_prediction_specific_outcome(
    session: AsyncSession, bet_market: BetMarket, payload: dict
) -> dict | None:
    if bet_market.bet_type == BetType.HEAD_TO_HEAD:
        team_a_id, team_b_id = payload.get("team_a_id"), payload.get("team_b_id")
        if team_a_id is None or team_b_id is None:
            return None
        standings = await get_standings(session, bet_market.tournament_id)
        rank_by_team = {s.team_id: s.rank for s in standings}
        if team_a_id not in rank_by_team or team_b_id not in rank_by_team:
            return None
        higher = team_a_id if rank_by_team[team_a_id] < rank_by_team[team_b_id] else team_b_id
        return {"higher_ranked_team_id": higher}

    if bet_market.bet_type == BetType.ROUND_WINNER:
        debate_id = payload.get("debate_id")
        if debate_id is None:
            return None
        winner_team_id = (
            await session.execute(
                select(DebateTeam.team_id)
                .join(Debate, DebateTeam.debate_id == Debate.id)
                .where(Debate.id == debate_id, DebateTeam.rank_in_debate == 1)
            )
        ).scalar_one_or_none()
        if winner_team_id is None:
            return None
        return {"debate_id": debate_id, "winning_team_id": winner_team_id}

    if bet_market.bet_type == BetType.ROUND_FULL_CALL:
        debate_id = payload.get("debate_id")
        if debate_id is None:
            return None
        rows = (
            await session.execute(
                select(DebateTeam.team_id, DebateTeam.rank_in_debate).where(
                    DebateTeam.debate_id == debate_id
                )
            )
        ).all()
        ranked = [(team_id, rank) for team_id, rank in rows if rank is not None]
        if len(ranked) < 4:
            return None
        ranked.sort(key=lambda entry: entry[1])
        return {"debate_id": debate_id, "actual_order": [team_id for team_id, _ in ranked]}

    return None


async def _get_final_speaker_ranking(session: AsyncSession, tournament_id: int) -> list[int]:
    """Speakers ranked by total speaker points across all preliminary debates. Unlike
    `domain.ranking`, this has no BP-specific tie-break cascade to apply -- it's a plain sum."""
    stmt = (
        select(SpeakerScore.speaker_id, func.sum(SpeakerScore.score))
        .join(DebateTeam, SpeakerScore.debate_team_id == DebateTeam.id)
        .join(Debate, DebateTeam.debate_id == Debate.id)
        .where(Debate.tournament_id == tournament_id, SpeakerScore.score.is_not(None))
        .group_by(SpeakerScore.speaker_id)
        .order_by(func.sum(SpeakerScore.score).desc())
    )
    rows = (await session.execute(stmt)).all()
    return [speaker_id for speaker_id, _total in rows]


async def settle_market(
    session: AsyncSession, bet_market: BetMarket, *, manual_outcome: dict | None = None
) -> bool:
    """Scores every open prediction on this market. Returns False (and settles nothing) if the
    market isn't resolvable yet -- callers should simply retry on a later scrape cycle."""
    if bet_market.status == BetMarketStatus.SETTLED:
        return True

    shared_outcome = manual_outcome or await build_market_outcome(session, bet_market)
    per_prediction = bet_market.bet_type in _PER_PREDICTION_BET_TYPES
    if shared_outcome is None and not per_prediction:
        return False

    predictions = (
        (await session.execute(select(Prediction).where(Prediction.bet_market_id == bet_market.id)))
        .scalars()
        .all()
    )

    any_settled = False
    for prediction in predictions:
        # Never re-score an already-settled prediction. A per-prediction market stays un-SETTLED
        # (returns False below) while ANY of its debates is still unresolved, so this same market
        # is revisited on every subsequent scrape cycle -- without this guard the predictions
        # that DID already resolve would have their payout credited to User.balance again on
        # every single cycle, minting balance out of nothing until the last debate resolved.
        if prediction.status == PredictionStatus.SETTLED:
            continue

        outcome = shared_outcome
        if per_prediction:
            outcome = await build_prediction_specific_outcome(
                session, bet_market, prediction.payload
            )
            if outcome is None:
                continue
        assert (
            outcome is not None
        )  # guaranteed by the shared_outcome check above when not per_prediction
        won = did_prediction_win(bet_market.bet_type, prediction.payload, outcome)
        payout = prediction.stake_amount * prediction.odds if won else 0.0
        prediction.points_awarded = payout
        prediction.status = PredictionStatus.SETTLED
        any_settled = True
        if won:
            user = await session.get(User, prediction.user_id)
            if user is not None:
                user.balance += payout

    # An OPEN market nobody has bet on yet must never be auto-settled: with no predictions the
    # `all(...)` check below is vacuously true, so a freshly-created round market would be marked
    # SETTLED by the very next scrape cycle -- killing it before anyone could place a bet. Once
    # an admin closes it (or it auto-closes), settling an empty market is just tidying up.
    if not predictions and bet_market.status == BetMarketStatus.OPEN:
        return False

    if per_prediction and not all(p.status == PredictionStatus.SETTLED for p in predictions):
        return (
            False  # some predictions (different debates) may still be pending -- keep market open
        )

    bet_market.status = BetMarketStatus.SETTLED
    bet_market.settled_at = datetime.datetime.now(datetime.timezone.utc)
    await session.flush()

    if any_settled:
        await recompute_leaderboard(session, bet_market.tournament_id)
    return True


def set_bet_market_status(bet_market: BetMarket, new_status: BetMarketStatus) -> BetMarket:
    """Applies an admin-requested `open<->closed` transition (see `PATCH /bet-markets/{id}` in
    the API contract). `settled` is never accepted here -- it's only ever set by
    `settle_market` -- and a market that's already settled can no longer be reopened/closed.

    Raises `ValueError` on any disallowed transition; the router maps that to HTTP 400.
    """
    if bet_market.status == BetMarketStatus.SETTLED:
        raise ValueError("a settled bet market's status can no longer be changed")
    if new_status == BetMarketStatus.SETTLED:
        raise ValueError("status can only be set to 'settled' by settling the market")
    bet_market.status = new_status
    return bet_market


async def recompute_leaderboard(session: AsyncSession, tournament_id: int) -> None:
    """Rewrites LeaderboardEntry from scratch off settled Predictions in this tournament --
    never hand-edited, always derived, so it can never drift out of sync with the predictions it
    summarizes.

    `total_points` here is this tournament's NET profit/loss (payout minus stake across every
    settled prediction on one of its markets), not the user's overall bankroll: `User.balance`
    is a single global wallet shared across every tournament a friend group tracks, so a
    per-tournament leaderboard has to look at that tournament's predictions specifically to say
    anything meaningful about "who called CMUDE 2025 the best." Unlike balance this CAN go
    negative -- it's a scoreboard of prediction skill, not a running cash total.
    """
    stmt = (
        select(
            Prediction.user_id,
            func.sum(Prediction.points_awarded - Prediction.stake_amount),
        )
        .join(BetMarket, Prediction.bet_market_id == BetMarket.id)
        .where(
            BetMarket.tournament_id == tournament_id, Prediction.status == PredictionStatus.SETTLED
        )
        .group_by(Prediction.user_id)
    )
    rows = (await session.execute(stmt)).all()
    ranked = sorted(rows, key=lambda r: -(r[1] or 0.0))

    now = datetime.datetime.now(datetime.timezone.utc)
    for i, (user_id, net_profit) in enumerate(ranked):
        await upsert_by_natural_key(
            session,
            LeaderboardEntry,
            lookup={"tournament_id": tournament_id, "user_id": user_id},
            values={"total_points": float(net_profit or 0.0), "rank": i + 1, "computed_at": now},
        )
