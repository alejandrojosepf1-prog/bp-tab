from app.models import Institution, Tournament
from app.models.enums import TournamentStatus
from app.repositories.upsert import upsert_by_natural_key


async def _make_tournament(db_session) -> Tournament:
    tournament = Tournament(
        name="CMUDE 2025",
        slug="cmude2025-open",
        source_base_url="https://cmude2025.calicotab.com",
        source_slug="open",
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add(tournament)
    await db_session.flush()
    return tournament


async def test_upsert_creates_when_missing(db_session) -> None:
    tournament = await _make_tournament(db_session)

    result = await upsert_by_natural_key(
        db_session,
        Institution,
        lookup={"tournament_id": tournament.id, "code": "PUCP"},
        values={"name": "Pontificia Universidad Católica del Perú", "region": "Perú"},
    )

    assert result.created is True
    assert result.changed is True
    assert result.instance.name == "Pontificia Universidad Católica del Perú"


async def test_upsert_is_a_noop_when_nothing_changed(db_session) -> None:
    tournament = await _make_tournament(db_session)
    values = {"name": "Pontificia Universidad Católica del Perú", "region": "Perú"}

    first = await upsert_by_natural_key(
        db_session,
        Institution,
        lookup={"tournament_id": tournament.id, "code": "PUCP"},
        values=values,
    )
    second = await upsert_by_natural_key(
        db_session,
        Institution,
        lookup={"tournament_id": tournament.id, "code": "PUCP"},
        values=values,
    )

    assert first.created is True
    assert second.created is False
    assert second.changed is False
    assert second.changed_fields == {}
    assert first.instance.id == second.instance.id


async def test_upsert_detects_and_applies_field_changes(db_session) -> None:
    tournament = await _make_tournament(db_session)
    await upsert_by_natural_key(
        db_session,
        Institution,
        lookup={"tournament_id": tournament.id, "code": "PUCP"},
        values={"name": "PUCP (old name)", "region": "Perú"},
    )

    result = await upsert_by_natural_key(
        db_session,
        Institution,
        lookup={"tournament_id": tournament.id, "code": "PUCP"},
        values={"name": "Pontificia Universidad Católica del Perú", "region": "Perú"},
    )

    assert result.created is False
    assert result.changed is True
    assert "name" in result.changed_fields
    assert result.changed_fields["name"]["old"] == "PUCP (old name)"
    assert result.changed_fields["name"]["new"] == "Pontificia Universidad Católica del Perú"
    assert "region" not in result.changed_fields
    assert result.instance.name == "Pontificia Universidad Católica del Perú"


async def test_upsert_never_creates_a_duplicate_row(db_session) -> None:
    from sqlalchemy import func, select

    tournament = await _make_tournament(db_session)
    for _ in range(3):
        await upsert_by_natural_key(
            db_session,
            Institution,
            lookup={"tournament_id": tournament.id, "code": "PUCP"},
            values={"name": "PUCP", "region": "Perú"},
        )

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(Institution)
            .filter_by(tournament_id=tournament.id, code="PUCP")
        )
    ).scalar_one()
    assert count == 1
