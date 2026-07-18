from app.models import Debate, DebateTeam, Round, Team, Tournament
from app.models.enums import BPPosition, RoundStage, RoundStatus, TournamentStatus
from app.services.tournament_service import refresh_tournament_status


async def _make_tournament(db_session) -> Tournament:
    tournament = Tournament(
        name="Test Cup",
        slug="test-cup",
        source_base_url="https://example.calicotab.com",
        source_slug="open",
        status=TournamentStatus.UPCOMING,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def test_status_stays_upcoming_with_no_rounds(db_session) -> None:
    tournament = await _make_tournament(db_session)
    await refresh_tournament_status(db_session, tournament)
    assert tournament.status == TournamentStatus.UPCOMING


async def test_status_becomes_in_progress_once_a_result_exists(db_session) -> None:
    tournament = await _make_tournament(db_session)
    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(round_1)
    await db_session.flush()
    team = Team(tournament_id=tournament.id, external_id=1, name="Team A")
    db_session.add(team)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    db_session.add(
        DebateTeam(
            debate_id=debate.id,
            team_id=team.id,
            position=BPPosition.OPENING_GOVERNMENT,
            rank_in_debate=1,
        )
    )
    await db_session.commit()

    await refresh_tournament_status(db_session, tournament)
    assert tournament.status == TournamentStatus.IN_PROGRESS


async def test_status_stays_in_progress_when_final_round_is_scheduled_but_unjudged(
    db_session,
) -> None:
    # The site's round-navigation menu lists every configured round -- including the Grand
    # Final -- from the very first scrape, long before it's drawn or played. Its mere presence
    # in the schedule must not flip the tournament's status away from what the actual
    # preliminary results say.
    tournament = await _make_tournament(db_session)
    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    final_round = Round(
        tournament_id=tournament.id,
        seq=10,
        name="Grand Final",
        stage=RoundStage.ELIMINATION,
        status=RoundStatus.DRAFT,
    )
    db_session.add_all([round_1, final_round])
    await db_session.flush()
    team = Team(tournament_id=tournament.id, external_id=1, name="Team A")
    db_session.add(team)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    db_session.add(
        DebateTeam(
            debate_id=debate.id,
            team_id=team.id,
            position=BPPosition.OPENING_GOVERNMENT,
            rank_in_debate=1,
        )
    )
    await db_session.commit()

    await refresh_tournament_status(db_session, tournament)
    assert tournament.status == TournamentStatus.IN_PROGRESS
    assert tournament.champion_team_id is None


async def test_status_becomes_eliminations_once_an_elimination_debate_is_judged(db_session) -> None:
    tournament = await _make_tournament(db_session)
    octos = Round(
        tournament_id=tournament.id,
        seq=10,
        name="Octofinals",
        stage=RoundStage.ELIMINATION,
        status=RoundStatus.COMPLETED,
    )
    final_round = Round(
        tournament_id=tournament.id,
        seq=13,
        name="Grand Final",
        stage=RoundStage.ELIMINATION,
        status=RoundStatus.DRAFT,
    )
    db_session.add_all([octos, final_round])
    await db_session.flush()
    team = Team(tournament_id=tournament.id, external_id=1, name="Team A")
    db_session.add(team)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=octos.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    db_session.add(
        DebateTeam(
            debate_id=debate.id,
            team_id=team.id,
            position=BPPosition.OPENING_GOVERNMENT,
            rank_in_debate=1,
        )
    )
    await db_session.commit()

    await refresh_tournament_status(db_session, tournament)
    assert tournament.status == TournamentStatus.ELIMINATIONS
    assert tournament.champion_team_id is None


async def test_champion_is_set_once_the_final_debate_is_judged(db_session) -> None:
    tournament = await _make_tournament(db_session)
    final_round = Round(
        tournament_id=tournament.id,
        seq=10,
        name="Grand Final",
        stage=RoundStage.ELIMINATION,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(final_round)
    await db_session.flush()
    teams = [
        Team(tournament_id=tournament.id, external_id=i, name=f"Team {i}") for i in range(1, 5)
    ]
    db_session.add_all(teams)
    await db_session.flush()
    debate = Debate(tournament_id=tournament.id, round_id=final_round.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    positions = [
        BPPosition.OPENING_GOVERNMENT,
        BPPosition.OPENING_OPPOSITION,
        BPPosition.CLOSING_GOVERNMENT,
        BPPosition.CLOSING_OPPOSITION,
    ]
    for i, (team, position) in enumerate(zip(teams, positions, strict=True), start=1):
        db_session.add(
            DebateTeam(debate_id=debate.id, team_id=team.id, position=position, rank_in_debate=i)
        )
    await db_session.commit()

    await refresh_tournament_status(db_session, tournament)
    assert tournament.status == TournamentStatus.COMPLETED
    assert tournament.champion_team_id == teams[0].id
