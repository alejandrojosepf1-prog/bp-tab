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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.odds import adaptive_temperature, ordered_sequence_odds, single_candidate_odds
from app.models import (
    BetMarket,
    Debate,
    DebateTeam,
    Institution,
    Round,
    Speaker,
    SpeakerScore,
    Team,
    TeamBreakCategory,
)
from app.models.enums import BetType, RoundStage
from app.services.ranking_service import get_standings

SPEAKER_POINTS_WEIGHT = 0.02  # total_speaker_points are ~10-30x team_points in magnitude
STRENGTH_OF_SCHEDULE_WEIGHT = 0.5

# BREAKOUT_TEAM ("equipo revelación") has no principled strength-based price -- picking the
# team that most exceeds ITS OWN prior expectation is a qualitative judgment call (see
# services/betting_service.py's build_market_outcome docstring for the same caveat on
# settlement), so it gets a flat, admin-tunable default instead of a computed one.
DEFAULT_BREAKOUT_TEAM_ODDS = 4.0


class UnpriceableMarketError(Exception):
    """Raised when a market/payload combination can't be priced yet (e.g. no debates played
    so there's no standings data to build a power rating from). Callers should surface this as
    a 400 -- betting can't open on a market with nothing to price odds from."""


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


async def quote_odds(session: AsyncSession, bet_market: BetMarket, payload: dict) -> float:
    """Prices `payload` (a candidate pick, same shape a Prediction.payload would have) against
    the market's bet_type. Raises UnpriceableMarketError if there's not enough data yet, or
    KeyError/ValueError (from app.domain.odds) if the payload names a candidate outside the
    currently-tracked field -- both are caller errors the router turns into 4xx responses."""
    bet_type = bet_market.bet_type

    if bet_type == BetType.BREAKOUT_TEAM:
        return float((bet_market.points_rule or {}).get("odds", DEFAULT_BREAKOUT_TEAM_ODDS))

    if bet_type == BetType.CHAMPION:
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        if not power:
            raise UnpriceableMarketError("no standings yet to price this market from")
        return single_candidate_odds(power, payload["team_id"])

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
        return single_candidate_odds(
            pair_power, payload["predicted_winner_id"], temperature=temperature
        )

    if bet_type == BetType.ROUND_WINNER:
        power = await compute_team_power_ratings(session, bet_market.tournament_id)
        debate_team_ids = (
            (
                await session.execute(
                    select(DebateTeam.team_id).where(DebateTeam.debate_id == payload["debate_id"])
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
        return single_candidate_odds(debate_power, payload["team_id"], temperature=temperature)

    if bet_type == BetType.BEST_INSTITUTION:
        institution_power = await compute_institution_power_ratings(
            session, bet_market.tournament_id
        )
        if not institution_power:
            raise UnpriceableMarketError("no standings yet to price this market from")
        return single_candidate_odds(institution_power, payload["institution_code"])

    if bet_type == BetType.TOP_N_BREAK:
        power = await compute_team_power_ratings(
            session, bet_market.tournament_id, break_category_id=bet_market.target_break_category_id
        )
        if not power:
            raise UnpriceableMarketError("no standings yet to price this market from")
        return ordered_sequence_odds(power, list(payload["team_ids"]))

    if bet_type == BetType.TOP_N_SPEAKERS:
        power = await compute_speaker_power_ratings(session, bet_market.tournament_id)
        if not power:
            raise UnpriceableMarketError("no speaker scores yet to price this market from")
        return ordered_sequence_odds(power, list(payload["speaker_ids"]))

    raise ValueError(f"no odds pricing implemented for bet type {bet_type!r}")
