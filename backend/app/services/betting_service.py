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

from app.domain.bet_outcomes import (
    did_prediction_win,
    did_speaker_points_sub_bet_win,
    did_sub_bet_win,
)
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
from app.services.odds_service import quote_odds, quote_sub_bet_odds
from app.services.ranking_service import get_standings

_PER_PREDICTION_BET_TYPES = {
    BetType.HEAD_TO_HEAD,
    BetType.ROUND_WINNER,
    BetType.ROUND_FULL_CALL,
    BetType.ROUND_HEAD_TO_HEAD,
}

# Bet types still creatable from the admin panel -- see app.models.enums.BetType for why
# top_n_break/top_n_speakers/head_to_head/breakout_team/best_institution are no longer here.
CREATABLE_BET_TYPES = (
    BetType.CHAMPION,
    BetType.ROUND_WINNER,
    BetType.ROUND_FULL_CALL,
    BetType.TOP_SPEAKER_POSITION,
    BetType.TEAM_BREAK,
    BetType.ROUND_HEAD_TO_HEAD,
)

_ROUND_SCOPED_BET_TYPES = {
    BetType.ROUND_WINNER, BetType.ROUND_FULL_CALL, BetType.ROUND_HEAD_TO_HEAD
}

# Bet types whose optional sub-bet resolves in the SAME instant as the base pick (see
# app.models.betting.Prediction's sub_bet_* docstring) -- all-or-nothing: missing the modifier
# zeroes out the whole payout, just like missing any leg of a parlay. ROUND_WINNER's
# speaker-points sub-bet is deliberately NOT here: it settles independently via
# `settle_pending_sub_bets`, since speaker points are often withheld until the tournament ends.
_SAME_TIMING_SUB_BET_TYPES = {BetType.ROUND_HEAD_TO_HEAD, BetType.TEAM_BREAK}

# Bet types whose optional sub-bet resolves LATER, independent of the base pick -- the base pays
# in full the moment the round result is known; the sub-bet is only marked OPEN then (never at
# placement time -- see place_prediction) and resolves separately via `settle_pending_sub_bets`,
# crediting an ADDITIONAL bonus on top of the base payout that already happened.
_DEFERRED_SUB_BET_TYPES = {BetType.ROUND_WINNER}


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
    if bet_type == BetType.ROUND_HEAD_TO_HEAD:
        # Scoped to the debate too (unlike legacy HEAD_TO_HEAD's global pair key): a round
        # can have many debates, so a user can hold one bet per pair PER debate, not just one
        # per pair across the whole round.
        a, b = sorted([payload["team_a_id"], payload["team_b_id"]])
        return f"debate:{payload['debate_id']}:pair:{a}:{b}"
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
    # None whenever payload has no "sub_bet" key or this bet_type has no modifier support --
    # see quote_sub_bet_odds and Prediction's sub_bet_* column docstring.
    sub_bet_odds = await quote_sub_bet_odds(session, bet_market, payload)
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
            "sub_bet_odds": sub_bet_odds,
            "sub_bet_status": None,
            "sub_bet_points_awarded": None,
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
        break_rows = (
            await session.execute(
                select(Break.team_id, Break.rank).where(
                    Break.tournament_id == bet_market.tournament_id,
                    Break.break_category_id == bet_market.target_break_category_id,
                )
            )
        ).all()
        if not break_rows:
            return None
        # break_rank_by_team/break_points_by_team feed the optional exact-rank/exact-points
        # sub-bet (see domain.bet_outcomes.did_sub_bet_win) -- breaking_team_ids alone (the
        # original, still-used key) only tells the base pick "did this team break at all".
        breaking_team_ids = [team_id for team_id, _rank in sorted(break_rows, key=lambda r: r[1])]
        rank_by_team = dict(break_rows)
        standings = await get_standings(
            session, bet_market.tournament_id, break_category_id=bet_market.target_break_category_id
        )
        points_by_team = {s.team_id: s.team_points for s in standings}
        return {
            "breaking_team_ids": breaking_team_ids,
            "break_rank_by_team": rank_by_team,
            "break_points_by_team": points_by_team,
        }

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
        rows = (
            await session.execute(
                select(DebateTeam.rank_in_debate, DebateTeam.advanced, DebateTeam.team_id)
                .join(Debate, DebateTeam.debate_id == Debate.id)
                .where(Debate.id == debate_id)
            )
        ).all()
        if not rows:
            return None
        ranked_winner = next((team_id for rank, _advanced, team_id in rows if rank == 1), None)
        if ranked_winner is not None:
            return {"debate_id": debate_id, "winning_team_id": ranked_winner}
        # Elimination fallback: no preliminary-style 1st-4th ranking exists for this debate --
        # see manual_results_service.apply_manual_advancing_teams, which records ONLY
        # advanced/not-advanced for a non-final out-round (BP eliminations advance 2 of 4
        # teams, so "who wins this debate" means "did MY team advance", not "who placed 1st",
        # which doesn't exist here). Falls through to this once a real ballot never arrives and
        # an admin resolves the debate manually instead.
        if any(advanced is None for _rank, advanced, _team_id in rows):
            return None  # still pending -- advance/rank status not fully known yet
        advancing_team_ids = [team_id for _rank, advanced, team_id in rows if advanced]
        if not advancing_team_ids:
            return None
        return {"debate_id": debate_id, "advancing_team_ids": advancing_team_ids}

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
            # Also the permanent state for an elimination debate resolved via
            # apply_manual_advancing_teams (advanced/not-advanced only, no full 1st-4th order)
            # -- a round_full_call market created against such a round simply never resolves
            # for that debate, same as any other missing-data case here.
            return None
        ranked.sort(key=lambda entry: entry[1])
        return {"debate_id": debate_id, "actual_order": [team_id for team_id, _ in ranked]}

    if bet_market.bet_type == BetType.ROUND_HEAD_TO_HEAD:
        debate_id = payload.get("debate_id")
        team_a_id, team_b_id = payload.get("team_a_id"), payload.get("team_b_id")
        if debate_id is None or team_a_id is None or team_b_id is None:
            return None
        rows = (
            await session.execute(
                select(DebateTeam.team_id, DebateTeam.rank_in_debate).where(
                    DebateTeam.debate_id == debate_id,
                    DebateTeam.team_id.in_([team_a_id, team_b_id]),
                )
            )
        ).all()
        rank_by_team = dict(rows)
        rank_a, rank_b = rank_by_team.get(team_a_id), rank_by_team.get(team_b_id)
        if rank_a is None or rank_b is None:
            return None
        higher_id = team_a_id if rank_a < rank_b else team_b_id
        return {
            "debate_id": debate_id,
            "higher_ranked_team_id": higher_id,
            "actual_rank_gap": abs(rank_a - rank_b),
        }

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


def _settle_prediction_payout(bet_type: BetType, prediction: Prediction, outcome: dict) -> float:
    """Base-pick payout, PLUS -- for the same-timing sub-bet types (`_SAME_TIMING_SUB_BET_TYPES`)
    -- the all-or-nothing combined payout if a modifier was attempted alongside it. Missing the
    base makes the modifier moot (no payout either way); missing the modifier after winning the
    base zeroes the WHOLE payout, same as missing any leg of a parlay -- the product decision
    behind this feature. Sets `sub_bet_status`/`sub_bet_points_awarded` as a side effect when a
    sub-bet was attempted; returns the total to credit to the user's balance.

    ROUND_WINNER's speaker-points sub-bet is the one deferred exception (`_DEFERRED_SUB_BET_TYPES`):
    the base pick pays on its own the moment the round result is known, and the sub-bet is only
    flipped to `sub_bet_status=OPEN` here (never at placement) -- its actual resolution happens
    much later, via `settle_pending_sub_bets`."""
    won = did_prediction_win(bet_type, prediction.payload, outcome)
    sub_bet_payload = prediction.payload.get("sub_bet")
    has_sub_bet = bool(sub_bet_payload) and prediction.sub_bet_odds is not None

    if has_sub_bet and bet_type in _DEFERRED_SUB_BET_TYPES:
        # The base pays on its own right now, independent of the sub-bet -- see
        # settle_pending_sub_bets for how the modifier resolves later. A losing base pick makes
        # the modifier moot forever (there's no "this team's speakers scored X" to check if this
        # team never won), so it's settled as a loss immediately instead of waiting on data that
        # could never change the outcome.
        if won:
            prediction.sub_bet_status = PredictionStatus.OPEN
        else:
            prediction.sub_bet_status = PredictionStatus.SETTLED
            prediction.sub_bet_points_awarded = 0.0
        return prediction.stake_amount * prediction.odds if won else 0.0

    if not has_sub_bet or bet_type not in _SAME_TIMING_SUB_BET_TYPES:
        return prediction.stake_amount * prediction.odds if won else 0.0

    if not won:
        prediction.sub_bet_status = PredictionStatus.SETTLED
        prediction.sub_bet_points_awarded = 0.0
        return 0.0

    sub_bet_won = did_sub_bet_win(bet_type, prediction.payload, outcome)
    payout = (
        prediction.stake_amount * prediction.odds * prediction.sub_bet_odds
        if sub_bet_won
        else 0.0
    )
    prediction.sub_bet_status = PredictionStatus.SETTLED
    prediction.sub_bet_points_awarded = payout
    return payout


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
        payout = _settle_prediction_payout(bet_market.bet_type, prediction, outcome)
        prediction.points_awarded = payout
        prediction.status = PredictionStatus.SETTLED
        any_settled = True
        if payout > 0:
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


async def settle_pending_sub_bets(session: AsyncSession, tournament_id: int) -> int:
    """Resolves ROUND_WINNER's deferred speaker-points sub-bet once real `SpeakerScore` data
    exists for the named speakers -- deliberately NOT filtered by `BetMarket.status`. By the
    time a tournament finally releases withheld speaker points, every round_winner market for
    it has typically been SETTLED for a long time already; `_settle_resolvable_markets` only
    ever looks at not-yet-settled markets, so it would never revisit these on its own. Called
    every scrape cycle (see `app.tasks.scrape_tasks.scrape_tournament_async`, right after
    `_settle_resolvable_markets`) -- auto-scrape keeps running indefinitely even after every
    market is settled, so a pending sub-bet just keeps getting rechecked until the data shows up.

    Returns how many sub-bets were resolved this call (0 most cycles)."""
    stmt = (
        select(Prediction)
        .join(BetMarket, Prediction.bet_market_id == BetMarket.id)
        .where(
            BetMarket.tournament_id == tournament_id,
            BetMarket.bet_type == BetType.ROUND_WINNER,
            Prediction.sub_bet_status == PredictionStatus.OPEN,
        )
    )
    predictions = (await session.execute(stmt)).scalars().all()
    if not predictions:
        return 0

    resolved = 0
    for prediction in predictions:
        sub_bet = prediction.payload.get("sub_bet") or {}
        entries = sub_bet.get("speaker_scores") or []
        speaker_ids = [e.get("speaker_id") for e in entries if e.get("speaker_id") is not None]
        debate_id = prediction.payload.get("debate_id")
        if not speaker_ids or debate_id is None:
            # Malformed payload -- nothing to ever wait for, settle as a loss now rather than
            # retrying forever.
            prediction.sub_bet_status = PredictionStatus.SETTLED
            prediction.sub_bet_points_awarded = 0.0
            resolved += 1
            continue

        rows = (
            await session.execute(
                select(SpeakerScore.speaker_id, SpeakerScore.score)
                .join(DebateTeam, SpeakerScore.debate_team_id == DebateTeam.id)
                .where(
                    DebateTeam.debate_id == debate_id,
                    SpeakerScore.speaker_id.in_(speaker_ids),
                )
            )
        ).all()
        score_by_speaker = dict(rows)
        if any(score_by_speaker.get(sid) is None for sid in speaker_ids):
            continue  # still withheld -- retried on a later cycle

        sub_bet_won = did_speaker_points_sub_bet_win(sub_bet, score_by_speaker)
        bonus = (
            prediction.stake_amount * prediction.odds * (prediction.sub_bet_odds - 1)
            if sub_bet_won
            else 0.0
        )
        prediction.sub_bet_status = PredictionStatus.SETTLED
        prediction.sub_bet_points_awarded = bonus
        resolved += 1
        if bonus > 0:
            # Folded into points_awarded (not just sub_bet_points_awarded) so this bonus counts
            # toward the leaderboard's net-profit sum without a separate SQL branch there -- see
            # Prediction.points_awarded's docstring, updated to describe this cumulative role.
            prediction.points_awarded = (prediction.points_awarded or 0.0) + bonus
            user = await session.get(User, prediction.user_id)
            if user is not None:
                user.balance += bonus

    if resolved:
        await recompute_leaderboard(session, tournament_id)
    return resolved


def _as_aware_utc(dt: datetime.datetime) -> datetime.datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=datetime.timezone.utc)


def set_bet_market_status(
    bet_market: BetMarket,
    new_status: BetMarketStatus,
    *,
    new_closes_at: datetime.datetime | None = None,
) -> BetMarket:
    """Applies an admin-requested `open<->closed` transition (see `PATCH /bet-markets/{id}` in
    the API contract). `settled` is never accepted here -- it's only ever set by
    `settle_market` -- and a market that's already settled can no longer be reopened/closed.

    Reopening (closed/settled-adjacent -> open) REQUIRES the resulting `closes_at` to be in the
    future. Without this, reopening a market whose deadline already passed left it looking open
    in the admin panel while `POST .../predictions` kept rejecting every bet with "not open for
    predictions" (`now >= closes_at` still held) -- the market appeared to close itself right
    back. `new_closes_at` lets the caller supply a fresh deadline in the same request; omitting
    it is only valid if the market's existing `closes_at` is still in the future (e.g. an admin
    closed it early and wants to reopen with time still left on the clock).

    Raises `ValueError` on any disallowed transition or a `closes_at` that isn't in the future;
    the router maps that to HTTP 400.
    """
    if bet_market.status == BetMarketStatus.SETTLED:
        raise ValueError("a settled bet market's status can no longer be changed")
    if new_status == BetMarketStatus.SETTLED:
        raise ValueError("status can only be set to 'settled' by settling the market")

    now = datetime.datetime.now(datetime.timezone.utc)
    if new_closes_at is not None:
        if _as_aware_utc(new_closes_at) <= now:
            raise ValueError("closes_at must be in the future")
        bet_market.closes_at = new_closes_at

    reopening = new_status == BetMarketStatus.OPEN and bet_market.status != BetMarketStatus.OPEN
    if reopening and _as_aware_utc(bet_market.closes_at) <= now:
        raise ValueError(
            "reopening this market requires setting a new closing time in the future -- "
            "its previous deadline has already passed"
        )

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
