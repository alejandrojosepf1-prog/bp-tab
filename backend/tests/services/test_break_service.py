from sqlalchemy import select

from app.models import (
    BreakCategory,
    BreakPrediction,
    Debate,
    DebateTeam,
    Round,
    Team,
    TeamBreakCategory,
    Tournament,
)
from app.models.enums import BPPosition, RoundStage, RoundStatus, TournamentStatus
from app.services.break_service import (
    recompute_break_predictions,
    team_break_exact_rank_probability,
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


async def test_recompute_break_predictions_persists_one_row_per_team(db_session) -> None:
    tournament = await _make_tournament(db_session)

    open_category = BreakCategory(
        tournament_id=tournament.id, name="Open", slug="open", break_size=2
    )
    db_session.add(open_category)
    await db_session.flush()

    round_1 = Round(
        tournament_id=tournament.id,
        seq=1,
        name="Round 1",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    round_2 = Round(
        tournament_id=tournament.id,
        seq=2,
        name="Round 2",
        stage=RoundStage.PRELIMINARY,
        status=RoundStatus.DRAFT,
    )
    db_session.add_all([round_1, round_2])
    await db_session.flush()

    teams = [
        Team(tournament_id=tournament.id, external_id=i, name=f"Team {i}") for i in range(1, 5)
    ]
    db_session.add_all(teams)
    await db_session.flush()
    for team in teams:
        db_session.add(TeamBreakCategory(team_id=team.id, break_category_id=open_category.id))

    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()

    placements = [
        (teams[0], BPPosition.OPENING_GOVERNMENT, 1),
        (teams[1], BPPosition.OPENING_OPPOSITION, 2),
        (teams[2], BPPosition.CLOSING_GOVERNMENT, 3),
        (teams[3], BPPosition.CLOSING_OPPOSITION, 4),
    ]
    for team, position, rank in placements:
        db_session.add(
            DebateTeam(debate_id=debate.id, team_id=team.id, position=position, rank_in_debate=rank)
        )
    await db_session.commit()

    report = await recompute_break_predictions(
        db_session, tournament.id, open_category.id, num_simulations=200
    )

    assert len(report) == 4
    by_id = {a.team_id: a for a in report}
    # Round 1 winner has an insurmountable lead for a 2-team break with 1 round left? Not quite
    # (3pts vs 0 with 1 round left: rivals can still reach 3) -- just check we got sane statuses.
    assert by_id[teams[0].id].status in {"safe", "alive"}
    assert by_id[teams[3].id].status in {"alive", "eliminated"}

    persisted = (await db_session.execute(select(BreakPrediction))).scalars().all()
    assert len(persisted) == 4
    assert {p.team_id for p in persisted} == {t.id for t in teams}


async def test_recompute_break_predictions_returns_empty_without_break_size(db_session) -> None:
    tournament = await _make_tournament(db_session)
    category = BreakCategory(
        tournament_id=tournament.id, name="Novice", slug="novice", break_size=None
    )
    db_session.add(category)
    await db_session.commit()

    report = await recompute_break_predictions(db_session, tournament.id, category.id)
    assert report == []


async def test_recompute_break_predictions_returns_empty_before_any_round_completes(
    db_session,
) -> None:
    tournament = await _make_tournament(db_session)
    category = BreakCategory(tournament_id=tournament.id, name="Open", slug="open", break_size=2)
    db_session.add(category)
    await db_session.commit()

    report = await recompute_break_predictions(db_session, tournament.id, category.id)
    assert report == []


async def test_team_break_exact_rank_probability_sums_to_one_after_round_completes(
    db_session,
) -> None:
    tournament = await _make_tournament(db_session)
    category = BreakCategory(tournament_id=tournament.id, name="Open", slug="open", break_size=2)
    db_session.add(category)
    await db_session.flush()

    round_1 = Round(
        tournament_id=tournament.id, seq=1, name="Round 1", stage=RoundStage.PRELIMINARY,
        status=RoundStatus.COMPLETED,
    )
    db_session.add(round_1)
    await db_session.flush()

    teams = [
        Team(tournament_id=tournament.id, external_id=i, name=f"Team {i}") for i in range(1, 5)
    ]
    db_session.add_all(teams)
    await db_session.flush()
    for team in teams:
        db_session.add(TeamBreakCategory(team_id=team.id, break_category_id=category.id))

    debate = Debate(tournament_id=tournament.id, round_id=round_1.id, external_id=1)
    db_session.add(debate)
    await db_session.flush()
    placements = [
        (teams[0], BPPosition.OPENING_GOVERNMENT, 1),
        (teams[1], BPPosition.OPENING_OPPOSITION, 2),
        (teams[2], BPPosition.CLOSING_GOVERNMENT, 3),
        (teams[3], BPPosition.CLOSING_OPPOSITION, 4),
    ]
    for team, position, rank in placements:
        db_session.add(
            DebateTeam(debate_id=debate.id, team_id=team.id, position=position, rank_in_debate=rank)
        )
    await db_session.commit()

    distribution = await team_break_exact_rank_probability(
        db_session, tournament.id, category.id, teams[0].id, num_simulations=500
    )
    assert distribution  # not empty -- Round 1 is complete, there's real data to simulate from
    assert abs(sum(distribution.values()) - 1.0) < 1e-9


async def test_team_break_exact_rank_probability_empty_before_any_round_completes(
    db_session,
) -> None:
    tournament = await _make_tournament(db_session)
    category = BreakCategory(tournament_id=tournament.id, name="Open", slug="open", break_size=2)
    db_session.add(category)
    await db_session.flush()
    team = Team(tournament_id=tournament.id, external_id=1, name="Team 1")
    db_session.add(team)
    await db_session.commit()

    distribution = await team_break_exact_rank_probability(
        db_session, tournament.id, category.id, team.id
    )
    assert distribution == {}


async def test_team_break_exact_rank_probability_empty_without_break_size(db_session) -> None:
    tournament = await _make_tournament(db_session)
    category = BreakCategory(
        tournament_id=tournament.id, name="Novice", slug="novice", break_size=None
    )
    db_session.add(category)
    team = Team(tournament_id=tournament.id, external_id=1, name="Team 1")
    db_session.add(team)
    await db_session.commit()

    distribution = await team_break_exact_rank_probability(
        db_session, tournament.id, category.id, team.id
    )
    assert distribution == {}
