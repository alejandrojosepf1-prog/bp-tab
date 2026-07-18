from app.domain.break_predictor import (
    build_break_report,
    classify_status,
    points_needed_for_safety,
)
from app.domain.ranking import TeamStanding


def _standing(
    team_id: int, points: int, *, firsts=0, seconds=0, thirds=0, fourths=0, rank=1
) -> TeamStanding:
    return TeamStanding(
        team_id=team_id,
        rank=rank,
        team_points=points,
        total_speaker_points=0.0,
        firsts=firsts,
        seconds=seconds,
        thirds=thirds,
        fourths=fourths,
        debates_played=firsts + seconds + thirds + fourths,
    )


def test_classify_status_safe_when_tournament_is_over() -> None:
    # Top 2 of [10, 8, 6, 4] with 0 rounds left and break_size=2 are unambiguously in.
    assert (
        classify_status(10, other_teams_points=[8, 6, 4], rounds_remaining=0, break_size=2)
        == "safe"
    )
    assert (
        classify_status(8, other_teams_points=[10, 6, 4], rounds_remaining=0, break_size=2)
        == "safe"
    )


def test_classify_status_eliminated_when_tournament_is_over() -> None:
    assert (
        classify_status(6, other_teams_points=[10, 8, 4], rounds_remaining=0, break_size=2)
        == "eliminated"
    )
    assert (
        classify_status(4, other_teams_points=[10, 8, 6], rounds_remaining=0, break_size=2)
        == "eliminated"
    )


def test_classify_status_alive_when_everyone_tied_with_one_round_left() -> None:
    # All 4 teams tied at 9pts, break_size=2, 1 round left: nobody is locked in or out yet.
    for _ in range(4):
        assert (
            classify_status(9, other_teams_points=[9, 9, 9], rounds_remaining=1, break_size=2)
            == "alive"
        )


def test_classify_status_safe_with_a_big_enough_lead_before_last_round() -> None:
    # Team has 18pts; the best any of the other 3 can reach is 9+3=12 < 18, and even the next
    # best rival tops out below the leader's current floor -- comfortably safe for top-2.
    assert (
        classify_status(18, other_teams_points=[9, 9, 9], rounds_remaining=1, break_size=2)
        == "safe"
    )


def test_classify_status_eliminated_when_ceiling_too_low() -> None:
    # Team has 3pts with 1 round left (ceiling 6); three rivals already sit above 6 -- no path in.
    assert (
        classify_status(3, other_teams_points=[20, 19, 18], rounds_remaining=1, break_size=2)
        == "eliminated"
    )


def test_points_needed_for_safety_is_none_once_already_safe() -> None:
    assert (
        points_needed_for_safety(10, other_teams_points=[8, 6, 4], rounds_remaining=0, break_size=2)
        is None
    )


def test_points_needed_for_safety_returns_a_small_positive_amount_when_close() -> None:
    needed = points_needed_for_safety(
        9, other_teams_points=[9, 9, 9], rounds_remaining=1, break_size=2
    )
    assert needed is not None
    assert 0 < needed <= 3


def test_build_break_report_assigns_probability_one_and_zero_at_the_extremes() -> None:
    standings = [
        _standing(1, 30, firsts=10),
        _standing(2, 24, firsts=8),
        _standing(3, 3, fourths=8),
        _standing(4, 0, fourths=10),
    ]
    report = build_break_report(standings, break_size=2, rounds_remaining=0)
    by_id = {a.team_id: a for a in report}
    assert by_id[1].status == "safe"
    assert by_id[1].probability == 1.0
    assert by_id[2].status == "safe"
    assert by_id[3].status == "eliminated"
    assert by_id[3].probability == 0.0
    assert by_id[4].status == "eliminated"
    assert by_id[4].probability == 0.0


def test_build_break_report_simulates_a_probability_for_alive_teams() -> None:
    standings = [
        _standing(1, 15, firsts=5),
        _standing(2, 9, firsts=3),
        _standing(3, 9, firsts=3),
        _standing(4, 3, fourths=5),
    ]
    report = build_break_report(standings, break_size=2, rounds_remaining=1, num_simulations=500)
    by_id = {a.team_id: a for a in report}
    assert by_id[1].status == "safe"
    # Teams 2 and 3 are tied and genuinely contesting the second break slot.
    assert by_id[2].status == "alive"
    assert by_id[3].status == "alive"
    assert 0.0 <= by_id[2].probability <= 1.0
    assert 0.0 <= by_id[3].probability <= 1.0
