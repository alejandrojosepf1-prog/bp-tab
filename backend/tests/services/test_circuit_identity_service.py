"""Exercises the matching rules documented in circuit_identity_service's module docstring:
institutions tolerate fuzzy matches (flagged for review), people never do."""

from app.models.circuit import CircuitPerson
from app.services.circuit_identity_service import (
    match_or_create_institution,
    match_or_create_person,
    normalize_name,
)


def test_normalize_name_ignores_case_accents_and_whitespace() -> None:
    assert normalize_name("  Pontificia Universidad Católica  ") == normalize_name(
        "PONTIFICIA UNIVERSIDAD CATOLICA"
    )


async def test_match_or_create_institution_creates_new_identity_on_first_sight(db_session) -> None:
    institution, needs_review = await match_or_create_institution(db_session, "PUCP", "PUCP")

    assert needs_review is False
    assert institution.name == "PUCP"
    assert institution.slug == "pucp"


async def test_match_or_create_institution_reuses_identity_on_exact_repeat(db_session) -> None:
    first, _ = await match_or_create_institution(db_session, "PUCP", "PUCP")
    second, needs_review = await match_or_create_institution(db_session, "PUCP", "PUCP")

    assert second.id == first.id
    assert needs_review is False


async def test_match_or_create_institution_fuzzy_match_flags_for_review(db_session) -> None:
    """A near-miss spelling of an already-known institution (a typo, not just an accent --
    normalize_name already makes accent-only variants an exact match, see the test above)
    links to the SAME identity, but comes back flagged so it can be confirmed rather than
    trusted blind (see the module docstring's confirmed=False rationale)."""
    original, _ = await match_or_create_institution(
        db_session, "Pontificia Universidad Catolica del Peru", "PUCP"
    )

    fuzzy, needs_review = await match_or_create_institution(
        db_session, "Pontifica Universidad Catolica del Peru", "PUCP-X"
    )

    assert fuzzy.id == original.id
    assert needs_review is True


async def test_match_or_create_institution_unrelated_name_creates_distinct_identity(
    db_session,
) -> None:
    pucp, _ = await match_or_create_institution(db_session, "PUCP", "PUCP")
    uniandes, _ = await match_or_create_institution(db_session, "Uniandes", "UNIANDES")

    assert uniandes.id != pucp.id


async def test_match_or_create_institution_does_not_merge_same_country_prefix_different_countries(
    db_session,
) -> None:
    """Regression test for a real false-positive found via a dry-run scrape against CMUDE 2025's
    actual institution list (see INSTITUTION_FUZZY_THRESHOLD's comment): a long shared prefix
    scores deceptively high on character-level similarity even though these are two different
    real universities in two different countries."""
    peru, _ = await match_or_create_institution(
        db_session, "Pontificia Universidad Catolica del Peru", "PUCP"
    )
    ecuador, _ = await match_or_create_institution(
        db_session, "Pontificia Universidad Catolica del Ecuador", "PUCE"
    )

    assert ecuador.id != peru.id


async def test_match_or_create_institution_does_not_merge_different_campuses(db_session) -> None:
    """Same false-positive pattern as above, found in the same dry run: different campuses of
    the same broader institution, sharing a long prefix."""
    toluca, _ = await match_or_create_institution(
        db_session,
        "Instituto Tecnologico y de Estudios Superiores de Monterrey Campus Toluca",
        "ITESM-TOL",
    )
    edomex, _ = await match_or_create_institution(
        db_session,
        "Instituto Tecnologico y de Estudios Superiores de Monterrey Campus Estado de Mexico",
        "ITESM-EDOMEX",
    )

    assert edomex.id != toluca.id


async def test_match_or_create_institution_does_not_merge_different_sedes(db_session) -> None:
    """Third false-positive from the same dry run: the differentiating word ("Piura" vs "Lima")
    is short relative to the shared prefix, but these are different institutions."""
    piura, _ = await match_or_create_institution(
        db_session, "Universidad de Piura Sede Piura", "UDEP-PIURA"
    )
    lima, _ = await match_or_create_institution(
        db_session, "Universidad de Piura Sede Lima", "UDEP-LIMA"
    )

    assert lima.id != piura.id


async def test_match_or_create_person_reuses_identity_on_exact_repeat(db_session) -> None:
    first = await match_or_create_person(db_session, "Juan Pérez")
    second = await match_or_create_person(db_session, "Juan Pérez")

    assert second.id == first.id


async def test_match_or_create_person_never_fuzzy_merges_distinct_names(db_session) -> None:
    """Unlike institutions, a near-miss spelling for a person creates a SEPARATE identity --
    merging two different people under one identity is the failure mode this matcher is
    designed to avoid (see module docstring)."""
    juan = await match_or_create_person(db_session, "Juan Perez")
    juana = await match_or_create_person(db_session, "Juana Perez")

    assert juan.id != juana.id


async def test_match_or_create_person_avoids_slug_collision(db_session) -> None:
    """Two different real people can end up needing the same base slug (a homonym who was
    never matched as the same alias, e.g. entered by an admin some other way) -- the new one
    still needs a slug that doesn't collide with the existing row."""
    db_session.add(CircuitPerson(display_name="Someone Else", slug="juan-perez"))
    await db_session.flush()

    person = await match_or_create_person(db_session, "Juan Perez")

    assert person.slug == "juan-perez-2"
