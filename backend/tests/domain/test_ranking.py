import pytest

from app.domain.ranking import DebateTeamRecord, compute_standings, team_points_for_rank


@pytest.mark.parametrize(("rank", "points"), [(1, 3), (2, 2), (3, 1), (4, 0)])
def test_team_points_for_rank(rank, points) -> None:
    assert team_points_for_rank(rank) == points


def test_team_points_for_rank_rejects_invalid_rank() -> None:
    with pytest.raises(ValueError):
        team_points_for_rank(5)


def test_compute_standings_ranks_by_points_then_speaks() -> None:
    records = [
        DebateTeamRecord(team_id=1, rank_in_debate=1, speaker_points=160),
        DebateTeamRecord(team_id=1, rank_in_debate=1, speaker_points=162),
        DebateTeamRecord(team_id=2, rank_in_debate=1, speaker_points=170),
        DebateTeamRecord(team_id=2, rank_in_debate=2, speaker_points=155),
    ]
    standings = compute_standings(records)
    # Team 1: 6 pts, team 2: 5 pts -- team 1 should rank first purely on points.
    assert [s.team_id for s in standings] == [1, 2]
    assert standings[0].team_points == 6
    assert standings[1].team_points == 5


def test_compute_standings_breaks_points_tie_with_speaker_points() -> None:
    records = [
        DebateTeamRecord(team_id=1, rank_in_debate=2, speaker_points=150),
        DebateTeamRecord(team_id=2, rank_in_debate=2, speaker_points=160),
    ]
    standings = compute_standings(records)
    assert [s.team_id for s in standings] == [2, 1]


def test_compute_standings_falls_back_to_firsts_when_points_and_speaks_tie() -> None:
    records = [
        # Team 1: one 1st (3pts) + one 4th (0pts) = 3pts, 1 first
        DebateTeamRecord(team_id=1, rank_in_debate=1, speaker_points=150),
        DebateTeamRecord(team_id=1, rank_in_debate=4, speaker_points=150),
        # Team 2: two 2nd-and-3rd-ish combos giving the same 3pts, 0 firsts
        DebateTeamRecord(team_id=2, rank_in_debate=2, speaker_points=150),
        DebateTeamRecord(team_id=2, rank_in_debate=3, speaker_points=150),
    ]
    standings = compute_standings(records)
    assert standings[0].team_points == standings[1].team_points == 3
    assert [s.team_id for s in standings] == [1, 2]  # team 1 wins on having more firsts


def test_compute_standings_ignores_speaker_points_when_any_are_missing() -> None:
    records = [
        DebateTeamRecord(team_id=1, rank_in_debate=1, speaker_points=None),
        DebateTeamRecord(team_id=2, rank_in_debate=1, speaker_points=999),
    ]
    standings = compute_standings(records)
    # Both have 3 points and tied firsts; without reliable speaks, team_id breaks the tie.
    assert [s.team_id for s in standings] == [1, 2]


def test_compute_standings_is_empty_for_no_records() -> None:
    assert compute_standings([]) == []
