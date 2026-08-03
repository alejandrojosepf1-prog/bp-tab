"""Exercises compute_positional_win_rates against synthetic debate results -- see CNADE 2026
Roadmap Pieza 2b. No real backfilled data exists yet; these pin the counting logic itself
(which stage uses rank_in_debate vs. advanced, and that an unjudged debate doesn't count)."""

from app.models.enums import BPPosition, RoundStage, TournamentStatus
from app.models.participants import Team
from app.models.rounds import Debate, DebateTeam, Round
from app.models.tournament import Tournament
from app.services.positional_stats_service import NO_DATA_WIN_RATE, compute_positional_win_rates


async def _make_tournament(db_session) -> Tournament:
    tournament = Tournament(
        name="Stats Test",
        slug="stats-test",
        source_base_url="https://stats-test.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _make_round(db_session, tournament: Tournament, *, stage: RoundStage, seq: int) -> Round:
    round_ = Round(tournament_id=tournament.id, seq=seq, name=f"Round {seq}", stage=stage)
    db_session.add(round_)
    await db_session.flush()
    return round_


async def _make_debate_team(
    db_session,
    tournament: Tournament,
    round_: Round,
    *,
    external_id: int,
    position: BPPosition,
    rank_in_debate: int | None = None,
    advanced: bool | None = None,
) -> DebateTeam:
    team = Team(tournament_id=tournament.id, external_id=external_id, name=f"Team {external_id}")
    db_session.add(team)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_.id, external_id=external_id)
    db_session.add(debate)
    await db_session.flush()
    debate_team = DebateTeam(
        debate_id=debate.id,
        team_id=team.id,
        position=position,
        rank_in_debate=rank_in_debate,
        advanced=advanced,
    )
    db_session.add(debate_team)
    await db_session.flush()
    return debate_team


async def test_returns_flat_prior_with_no_historical_data(db_session) -> None:
    rates = await compute_positional_win_rates(db_session, stage=RoundStage.PRELIMINARY)

    assert rates == {position: NO_DATA_WIN_RATE for position in BPPosition}


async def test_preliminary_win_rate_uses_rank_in_debate(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_ = await _make_round(db_session, tournament, stage=RoundStage.PRELIMINARY, seq=1)
    # OG wins twice, OO never wins across the same two (synthetic, one-room-per-debate) samples.
    await _make_debate_team(
        db_session, tournament, round_, external_id=1, position=BPPosition.OPENING_GOVERNMENT, rank_in_debate=1
    )
    await _make_debate_team(
        db_session, tournament, round_, external_id=2, position=BPPosition.OPENING_OPPOSITION, rank_in_debate=2
    )
    await _make_debate_team(
        db_session, tournament, round_, external_id=3, position=BPPosition.OPENING_GOVERNMENT, rank_in_debate=1
    )
    await _make_debate_team(
        db_session, tournament, round_, external_id=4, position=BPPosition.OPENING_OPPOSITION, rank_in_debate=3
    )

    rates = await compute_positional_win_rates(db_session, stage=RoundStage.PRELIMINARY)

    assert rates[BPPosition.OPENING_GOVERNMENT] == 1.0
    assert rates[BPPosition.OPENING_OPPOSITION] == 0.0
    # No observations at all for these two -- flat prior, not zero.
    assert rates[BPPosition.CLOSING_GOVERNMENT] == NO_DATA_WIN_RATE
    assert rates[BPPosition.CLOSING_OPPOSITION] == NO_DATA_WIN_RATE


async def test_elimination_win_rate_uses_advanced_not_rank(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_ = await _make_round(db_session, tournament, stage=RoundStage.ELIMINATION, seq=9)
    # rank_in_debate intentionally left NULL -- elimination rounds are judged via `advanced`.
    await _make_debate_team(
        db_session, tournament, round_, external_id=1, position=BPPosition.CLOSING_GOVERNMENT, advanced=True
    )
    await _make_debate_team(
        db_session, tournament, round_, external_id=2, position=BPPosition.CLOSING_OPPOSITION, advanced=False
    )

    rates = await compute_positional_win_rates(db_session, stage=RoundStage.ELIMINATION)

    assert rates[BPPosition.CLOSING_GOVERNMENT] == 1.0
    assert rates[BPPosition.CLOSING_OPPOSITION] == 0.0


async def test_unjudged_debate_is_excluded_not_counted_as_a_loss(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_ = await _make_round(db_session, tournament, stage=RoundStage.PRELIMINARY, seq=1)
    await _make_debate_team(
        db_session, tournament, round_, external_id=1, position=BPPosition.OPENING_GOVERNMENT, rank_in_debate=None
    )

    rates = await compute_positional_win_rates(db_session, stage=RoundStage.PRELIMINARY)

    assert rates[BPPosition.OPENING_GOVERNMENT] == NO_DATA_WIN_RATE


async def test_stages_are_computed_independently(db_session) -> None:
    tournament = await _make_tournament(db_session)
    prelim = await _make_round(db_session, tournament, stage=RoundStage.PRELIMINARY, seq=1)
    elim = await _make_round(db_session, tournament, stage=RoundStage.ELIMINATION, seq=9)
    await _make_debate_team(
        db_session, tournament, prelim, external_id=1, position=BPPosition.OPENING_GOVERNMENT, rank_in_debate=4
    )
    await _make_debate_team(
        db_session, tournament, elim, external_id=2, position=BPPosition.OPENING_GOVERNMENT, advanced=True
    )

    prelim_rates = await compute_positional_win_rates(db_session, stage=RoundStage.PRELIMINARY)
    elim_rates = await compute_positional_win_rates(db_session, stage=RoundStage.ELIMINATION)

    assert prelim_rates[BPPosition.OPENING_GOVERNMENT] == 0.0
    assert elim_rates[BPPosition.OPENING_GOVERNMENT] == 1.0
