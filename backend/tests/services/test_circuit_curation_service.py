"""Exercises the two admin curation gaps circuit_curation_service closes: fuzzy-matched
institutions awaiting confirmation, and teams the prefix heuristic never linked at all."""

from app.models.enums import TournamentStatus
from app.models.participants import Institution, Team
from app.models.tournament import Tournament
from app.services.circuit_curation_service import (
    assign_team_institution,
    list_review_queue,
    list_unassigned_teams,
    resolve_review_item,
)
from app.services.circuit_identity_service import match_or_create_institution


async def _make_tournament(db_session, slug: str = "test-open") -> Tournament:
    tournament = Tournament(
        name="Test Tournament",
        slug=slug,
        source_base_url="https://test.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def _ingest_institution(db_session, tournament: Tournament, name: str, code: str) -> Institution:
    """Mirrors what services.ingestion._ingest_institutions actually does: match the circuit
    identity, then create the tournament-scoped Institution row pointing at it. The bare
    match_or_create_institution call alone (as circuit_identity_service's own tests use it)
    never creates an Institution row, so circuit_curation_service -- which queries Institution,
    not just the identity tables -- has nothing to find without this."""
    circuit_institution, _ = await match_or_create_institution(db_session, name, code)
    institution = Institution(
        tournament_id=tournament.id,
        code=code,
        name=name,
        circuit_institution_id=circuit_institution.id,
    )
    db_session.add(institution)
    await db_session.flush()
    return institution


async def test_list_review_queue_empty_with_no_fuzzy_matches(db_session) -> None:
    tournament = await _make_tournament(db_session)
    await _ingest_institution(db_session, tournament, "PUCP", "PUCP")

    assert await list_review_queue(db_session) == []


async def test_list_review_queue_surfaces_a_fuzzy_match(db_session) -> None:
    tournament = await _make_tournament(db_session)
    await _ingest_institution(db_session, tournament, "Pontificia Universidad Catolica del Peru", "PUCP")
    flagged = await _ingest_institution(
        db_session, tournament, "Pontifica Universidad Catolica del Peru", "PUCP-X"
    )

    queue = await list_review_queue(db_session)

    assert len(queue) == 1
    assert queue[0].institution.id == flagged.id
    assert queue[0].circuit_institution.name == "Pontificia Universidad Catolica del Peru"


async def test_resolve_review_item_confirm_clears_the_queue(db_session) -> None:
    tournament = await _make_tournament(db_session)
    original = await _ingest_institution(
        db_session, tournament, "Pontificia Universidad Catolica del Peru", "PUCP"
    )
    flagged = await _ingest_institution(
        db_session, tournament, "Pontifica Universidad Catolica del Peru", "PUCP-X"
    )

    await resolve_review_item(
        db_session,
        flagged,
        circuit_institution_id=original.circuit_institution_id,
        new_institution_name=None,
        new_institution_region=None,
    )

    assert await list_review_queue(db_session) == []
    assert flagged.circuit_institution_id == original.circuit_institution_id


async def test_resolve_review_item_reassigns_to_a_different_existing_institution(db_session) -> None:
    tournament = await _make_tournament(db_session)
    await _ingest_institution(db_session, tournament, "Universidad A", "A")
    correct = await _ingest_institution(db_session, tournament, "Universidad B", "B")
    # "Universidad A2" scores 0.963 against "Universidad A" (>= the 0.95 threshold) -- a real
    # fuzzy match, not a hand-picked coincidence: see circuit_identity_service's threshold comment.
    flagged = await _ingest_institution(db_session, tournament, "Universidad A2", "A2")
    assert len(await list_review_queue(db_session)) == 1

    target = await resolve_review_item(
        db_session,
        flagged,
        circuit_institution_id=correct.circuit_institution_id,
        new_institution_name=None,
        new_institution_region=None,
    )

    assert target.id == correct.circuit_institution_id
    assert flagged.circuit_institution_id == correct.circuit_institution_id
    assert await list_review_queue(db_session) == []


async def test_resolve_review_item_creates_a_brand_new_institution(db_session) -> None:
    tournament = await _make_tournament(db_session)
    await _ingest_institution(db_session, tournament, "Universidad A", "A")
    flagged = await _ingest_institution(db_session, tournament, "Universidad A2", "A2")

    target = await resolve_review_item(
        db_session,
        flagged,
        circuit_institution_id=None,
        new_institution_name="Universidad Genuinamente Distinta",
        new_institution_region="Perú",
    )

    assert target.name == "Universidad Genuinamente Distinta"
    assert target.region == "Perú"
    assert flagged.circuit_institution_id == target.id
    assert await list_review_queue(db_session) == []


async def test_list_unassigned_teams_finds_teams_without_institution(db_session) -> None:
    tournament = await _make_tournament(db_session)
    institution = await _ingest_institution(db_session, tournament, "PUCP", "PUCP")

    unassigned = Team(tournament_id=tournament.id, external_id=1, name="Weird Name FM")
    assigned = Team(
        tournament_id=tournament.id,
        external_id=2,
        name="PUCP FM",
        institution_id=institution.id,
    )
    db_session.add_all([unassigned, assigned])
    await db_session.flush()

    result = await list_unassigned_teams(db_session)

    assert {t.id for t in result} == {unassigned.id}


async def test_assign_team_institution_creates_institution_row_when_missing(db_session) -> None:
    tournament = await _make_tournament(db_session)
    team = Team(tournament_id=tournament.id, external_id=1, name="Weird Name FM")
    db_session.add(team)
    await db_session.flush()
    circuit_institution, _ = await match_or_create_institution(db_session, "PUCP", "PUCP")

    institution = await assign_team_institution(
        db_session,
        team,
        circuit_institution_id=circuit_institution.id,
        new_institution_name=None,
        new_institution_region=None,
    )

    assert team.institution_id == institution.id
    assert institution.tournament_id == tournament.id
    assert institution.circuit_institution_id == circuit_institution.id


async def test_assign_team_institution_reuses_existing_institution_row(db_session) -> None:
    tournament = await _make_tournament(db_session)
    existing_institution = await _ingest_institution(db_session, tournament, "PUCP", "PUCP")
    team = Team(tournament_id=tournament.id, external_id=1, name="PUCP Segundo")
    db_session.add(team)
    await db_session.flush()

    institution = await assign_team_institution(
        db_session,
        team,
        circuit_institution_id=existing_institution.circuit_institution_id,
        new_institution_name=None,
        new_institution_region=None,
    )

    assert institution.id == existing_institution.id


async def test_assign_team_institution_with_new_institution_name(db_session) -> None:
    tournament = await _make_tournament(db_session)
    team = Team(tournament_id=tournament.id, external_id=1, name="Equipo Sin Match")
    db_session.add(team)
    await db_session.flush()

    institution = await assign_team_institution(
        db_session,
        team,
        circuit_institution_id=None,
        new_institution_name="Universidad Nueva",
        new_institution_region="Panamá",
    )

    assert team.institution_id == institution.id
    assert institution.name == "Universidad Nueva"
    assert institution.region == "Panamá"
