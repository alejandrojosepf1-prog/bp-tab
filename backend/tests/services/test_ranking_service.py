from app.models import BreakCategory, Debate, DebateTeam, Round, Team, TeamBreakCategory, Tournament
from app.models.enums import BPPosition, RoundStage, RoundStatus, TournamentStatus
from app.services.ranking_service import (
    get_latest_completed_round_seq,
    get_standings,
    get_total_preliminary_rounds,
)


async def _make_tournament(db_session) -> Tournament:
    tournament = Tournament(
        name="Test Cup",
        slug="test-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _make_round(
    db_session, tournament: Tournament, seq: int, *, stage=RoundStage.PRELIMINARY
) -> Round:
    round_ = Round(
        tournament_id=tournament.id,
        seq=seq,
        name=f"Round {seq}",
        stage=stage,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(round_)
    await db_session.flush()
    return round_


async def _make_debate_with_results(
    db_session, tournament: Tournament, round_: Round, placements: dict
) -> Debate:
    """placements: {team: (position, rank_in_debate, speaker_points)}"""
    debate = Debate(
        tournament_id=tournament.id, round_id=round_.id, external_id=round_.seq * 1000 + 1
    )
    db_session.add(debate)
    await db_session.flush()
    for team, (position, rank, speaks) in placements.items():
        db_session.add(
            DebateTeam(
                debate_id=debate.id,
                team_id=team.id,
                position=position,
                rank_in_debate=rank,
                speaker_points_total=speaks,
            )
        )
    await db_session.flush()
    return debate


async def _make_team(db_session, tournament: Tournament, external_id: int, name: str) -> Team:
    team = Team(tournament_id=tournament.id, external_id=external_id, name=name)
    db_session.add(team)
    await db_session.flush()
    return team


async def test_get_standings_reflects_debate_team_rows(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_1 = await _make_round(db_session, tournament, 1)
    team_a = await _make_team(db_session, tournament, 1, "Team A")
    team_b = await _make_team(db_session, tournament, 2, "Team B")
    team_c = await _make_team(db_session, tournament, 3, "Team C")
    team_d = await _make_team(db_session, tournament, 4, "Team D")

    await _make_debate_with_results(
        db_session,
        tournament,
        round_1,
        {
            team_a: (BPPosition.OPENING_GOVERNMENT, 1, 160),
            team_b: (BPPosition.OPENING_OPPOSITION, 2, 155),
            team_c: (BPPosition.CLOSING_GOVERNMENT, 3, 150),
            team_d: (BPPosition.CLOSING_OPPOSITION, 4, 145),
        },
    )
    await db_session.commit()

    standings = await get_standings(db_session, tournament.id)
    assert [s.team_id for s in standings] == [team_a.id, team_b.id, team_c.id, team_d.id]
    assert standings[0].team_points == 3
    assert standings[-1].team_points == 0


async def test_get_standings_filters_by_break_category(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_1 = await _make_round(db_session, tournament, 1)
    team_a = await _make_team(db_session, tournament, 1, "Team A")
    team_b = await _make_team(db_session, tournament, 2, "Team B")
    team_c = await _make_team(db_session, tournament, 3, "Team C")
    team_d = await _make_team(db_session, tournament, 4, "Team D")

    esl = BreakCategory(tournament_id=tournament.id, name="ESL", slug="esl")
    db_session.add(esl)
    await db_session.flush()
    db_session.add(TeamBreakCategory(team_id=team_b.id, break_category_id=esl.id))
    db_session.add(TeamBreakCategory(team_id=team_d.id, break_category_id=esl.id))

    await _make_debate_with_results(
        db_session,
        tournament,
        round_1,
        {
            team_a: (BPPosition.OPENING_GOVERNMENT, 1, 160),
            team_b: (BPPosition.OPENING_OPPOSITION, 2, 155),
            team_c: (BPPosition.CLOSING_GOVERNMENT, 3, 150),
            team_d: (BPPosition.CLOSING_OPPOSITION, 4, 145),
        },
    )
    await db_session.commit()

    esl_standings = await get_standings(db_session, tournament.id, break_category_id=esl.id)
    assert {s.team_id for s in esl_standings} == {team_b.id, team_d.id}


async def test_get_standings_ignores_elimination_rounds(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_1 = await _make_round(db_session, tournament, 1)
    final_round = await _make_round(db_session, tournament, 2, stage=RoundStage.ELIMINATION)
    team_a = await _make_team(db_session, tournament, 1, "Team A")
    team_b = await _make_team(db_session, tournament, 2, "Team B")
    team_c = await _make_team(db_session, tournament, 3, "Team C")
    team_d = await _make_team(db_session, tournament, 4, "Team D")

    await _make_debate_with_results(
        db_session,
        tournament,
        round_1,
        {
            team_a: (BPPosition.OPENING_GOVERNMENT, 1, 160),
            team_b: (BPPosition.OPENING_OPPOSITION, 2, 155),
            team_c: (BPPosition.CLOSING_GOVERNMENT, 3, 150),
            team_d: (BPPosition.CLOSING_OPPOSITION, 4, 145),
        },
    )
    await _make_debate_with_results(
        db_session,
        tournament,
        final_round,
        {
            team_d: (BPPosition.OPENING_GOVERNMENT, 1, 200),
            team_c: (BPPosition.OPENING_OPPOSITION, 2, 190),
            team_b: (BPPosition.CLOSING_GOVERNMENT, 3, 180),
            team_a: (BPPosition.CLOSING_OPPOSITION, 4, 170),
        },
    )
    await db_session.commit()

    standings = await get_standings(db_session, tournament.id)
    # Team A should still be ranked 1st -- the elimination round's reversed placements must
    # not leak into the preliminary standings.
    assert standings[0].team_id == team_a.id


async def test_get_latest_completed_round_and_total(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_1 = await _make_round(db_session, tournament, 1)
    await _make_round(db_session, tournament, 2)  # drawn but no results yet
    team_a = await _make_team(db_session, tournament, 1, "Team A")
    team_b = await _make_team(db_session, tournament, 2, "Team B")
    team_c = await _make_team(db_session, tournament, 3, "Team C")
    team_d = await _make_team(db_session, tournament, 4, "Team D")
    await _make_debate_with_results(
        db_session,
        tournament,
        round_1,
        {
            team_a: (BPPosition.OPENING_GOVERNMENT, 1, 160),
            team_b: (BPPosition.OPENING_OPPOSITION, 2, 155),
            team_c: (BPPosition.CLOSING_GOVERNMENT, 3, 150),
            team_d: (BPPosition.CLOSING_OPPOSITION, 4, 145),
        },
    )
    await db_session.commit()

    assert await get_latest_completed_round_seq(db_session, tournament.id) == 1
    assert await get_total_preliminary_rounds(db_session, tournament.id) == 2
