from app.models import Base, Institution, Speaker, Team, Tournament
from app.models.enums import TournamentStatus


def test_all_domain_tables_are_registered() -> None:
    expected = {
        "tournaments",
        "circuit_institutions",
        "circuit_institution_aliases",
        "circuit_people",
        "circuit_person_aliases",
        "break_categories",
        "speaker_categories",
        "institutions",
        "teams",
        "team_break_categories",
        "speakers",
        "speaker_category_links",
        "adjudicators",
        "rounds",
        "rooms",
        "debates",
        "debate_teams",
        "speaker_scores",
        "debate_adjudicators",
        "results",
        "breaks",
        "break_predictions",
        "adjudicator_breaks",
        "users",
        "bet_markets",
        "predictions",
        "leaderboard_entries",
        "tournament_balances",
        "scrape_logs",
        "change_events",
        "prize_events",
        "prize_entries",
        "odds_snapshots",
        "transactions",
    }
    assert expected == set(Base.metadata.tables.keys())


async def test_tournament_team_speaker_roundtrip(db_session) -> None:
    tournament = Tournament(
        name="CMUDE 2025",
        slug="cmude2025-open",
        source_base_url="https://cmude2025.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()

    institution = Institution(tournament_id=tournament.id, code="PUCP", name="PUCP", region="Perú")
    db_session.add(institution)
    await db_session.flush()

    team = Team(
        tournament_id=tournament.id,
        external_id=259867,
        name="PUCP FM",
        emoji="\U0001f4f1",
        institution_id=institution.id,
    )
    db_session.add(team)
    await db_session.flush()

    speaker = Speaker(
        tournament_id=tournament.id, external_id=1001, team_id=team.id, name="Fernanda Crousillat"
    )
    db_session.add(speaker)
    await db_session.commit()

    await db_session.refresh(team, attribute_names=["speakers", "institution"])
    assert team.institution.name == "PUCP"
    assert [s.name for s in team.speakers] == ["Fernanda Crousillat"]
