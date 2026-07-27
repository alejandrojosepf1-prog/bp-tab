import datetime

from app.models import LeaderboardEntry, Tournament, User
from app.models.enums import TournamentStatus, UserRole
from app.services.global_leaderboard_service import compute_global_leaderboard

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


async def _make_tournament(db_session, name: str) -> Tournament:
    tournament = Tournament(
        name=name,
        slug=name.lower().replace(" ", "-"),
        source_base_url="https://example.calicotab.com",
        source_slug=name.lower(),
        status=TournamentStatus.COMPLETED,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _make_user(db_session, email: str, display_name: str, balance: float = 100.0) -> User:
    user = User(
        email=email, password_hash="x", display_name=display_name, role=UserRole.USER,
        balance=balance,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_compute_global_leaderboard_sums_across_tournaments(db_session) -> None:
    t1 = await _make_tournament(db_session, "Cup One")
    t2 = await _make_tournament(db_session, "Cup Two")
    alice = await _make_user(db_session, "alice@x.com", "Alice", balance=150.0)
    bob = await _make_user(db_session, "bob@x.com", "Bob", balance=80.0)
    await db_session.commit()

    db_session.add_all(
        [
            LeaderboardEntry(
                tournament_id=t1.id, user_id=alice.id, total_points=50.0, rank=1, computed_at=NOW
            ),
            LeaderboardEntry(
                tournament_id=t2.id, user_id=alice.id, total_points=20.0, rank=2, computed_at=NOW
            ),
            LeaderboardEntry(
                tournament_id=t1.id, user_id=bob.id, total_points=100.0, rank=1, computed_at=NOW
            ),
        ]
    )
    await db_session.commit()

    entries = await compute_global_leaderboard(db_session)

    assert [e.display_name for e in entries] == ["Bob", "Alice"]  # Bob's 100 > Alice's 70
    bob_entry, alice_entry = entries
    assert bob_entry.total_points == 100.0
    assert bob_entry.tournaments_played == 1
    assert bob_entry.balance == 80.0
    assert alice_entry.total_points == 70.0
    assert alice_entry.tournaments_played == 2
    assert alice_entry.balance == 150.0


async def test_compute_global_leaderboard_excludes_users_with_no_settled_history(
    db_session,
) -> None:
    await _make_user(db_session, "never_bet@x.com", "Never Bet")
    await db_session.commit()

    entries = await compute_global_leaderboard(db_session)

    assert entries == []


async def test_compute_global_leaderboard_ties_break_by_display_name(db_session) -> None:
    tournament = await _make_tournament(db_session, "Cup")
    zed = await _make_user(db_session, "zed@x.com", "Zed")
    amy = await _make_user(db_session, "amy@x.com", "Amy")
    await db_session.commit()

    db_session.add_all(
        [
            LeaderboardEntry(
                tournament_id=tournament.id, user_id=zed.id, total_points=10.0, rank=1,
                computed_at=NOW,
            ),
            LeaderboardEntry(
                tournament_id=tournament.id, user_id=amy.id, total_points=10.0, rank=1,
                computed_at=NOW,
            ),
        ]
    )
    await db_session.commit()

    entries = await compute_global_leaderboard(db_session)

    assert [e.display_name for e in entries] == ["Amy", "Zed"]
