from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CircuitInstitution, CircuitInstitutionAlias, Institution, Round, Team, Tournament
from app.models.enums import MotionCategory, RoundStage, RoundStatus, TournamentStatus


async def _make_tournament(db_session: AsyncSession, **kwargs) -> Tournament:
    tournament = Tournament(
        name=kwargs.pop("name", "CMUDE 2024"),
        slug=kwargs.pop("slug", "cmude-2024"),
        source_base_url=kwargs.pop("source_base_url", "https://cmude2024.calicotab.com"),
        source_slug=kwargs.pop("source_slug", "open"),
        status=kwargs.pop("status", TournamentStatus.COMPLETED),
        **kwargs,
    )
    db_session.add(tournament)
    await db_session.commit()
    await db_session.refresh(tournament)
    return tournament


async def test_list_circuit_institutions_is_public(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(CircuitInstitution(name="PUCP", slug="pucp", region="Perú"))
    await db_session.commit()

    response = await client.get("/api/v1/circuit/institutions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "PUCP"
    assert body[0]["region"] == "Perú"


async def test_get_unknown_circuit_institution_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/circuit/institutions/does-not-exist")
    assert response.status_code == 404


async def test_circuit_institution_detail_aggregates_appearances_across_tournaments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The whole point of the circuit identity layer: one institution's teams across
    DIFFERENT tournament years show up as one unified history, newest first, with the
    champion flag set correctly per year."""
    circuit_institution = CircuitInstitution(name="PUCP", slug="pucp", region="Perú")
    db_session.add(circuit_institution)
    await db_session.flush()
    db_session.add(
        CircuitInstitutionAlias(circuit_institution_id=circuit_institution.id, alias="pucp")
    )

    t2024 = await _make_tournament(db_session, name="CMUDE 2024", slug="cmude-2024", year=2024)
    t2023 = await _make_tournament(
        db_session,
        name="CMUDE 2023",
        slug="cmude-2023",
        source_base_url="https://cmude2023.calicotab.com",
        year=2023,
    )

    inst_2024 = Institution(
        tournament_id=t2024.id, code="PUCP", name="PUCP", circuit_institution_id=circuit_institution.id
    )
    inst_2023 = Institution(
        tournament_id=t2023.id, code="PUCP", name="PUCP", circuit_institution_id=circuit_institution.id
    )
    db_session.add_all([inst_2024, inst_2023])
    await db_session.flush()

    team_2024 = Team(tournament_id=t2024.id, external_id=1, name="PUCP FM", institution_id=inst_2024.id)
    team_2023 = Team(tournament_id=t2023.id, external_id=1, name="PUCP JP", institution_id=inst_2023.id)
    db_session.add_all([team_2024, team_2023])
    await db_session.flush()

    t2024.champion_team_id = team_2024.id
    await db_session.commit()

    response = await client.get("/api/v1/circuit/institutions/pucp")
    assert response.status_code == 200
    body = response.json()
    assert [a["tournament_year"] for a in body["appearances"]] == [2024, 2023]
    assert body["appearances"][0]["was_champion"] is True
    assert body["appearances"][0]["team_names"] == ["PUCP FM"]
    assert body["appearances"][1]["was_champion"] is False


async def test_get_tournament_by_slug(client: AsyncClient, db_session: AsyncSession) -> None:
    tournament = await _make_tournament(db_session, year=2024)

    response = await client.get(f"/api/v1/tournaments/slug/{tournament.slug}")
    assert response.status_code == 200
    assert response.json()["id"] == tournament.id
    assert response.json()["year"] == 2024


async def test_get_unknown_tournament_slug_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tournaments/slug/does-not-exist")
    assert response.status_code == 404


async def test_motions_only_includes_completed_tournaments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    completed = await _make_tournament(
        db_session, name="CMUDE 2024", slug="cmude-2024", year=2024, status=TournamentStatus.COMPLETED
    )
    in_progress = await _make_tournament(
        db_session,
        name="CMUDE 2026",
        slug="cmude-2026",
        source_base_url="https://cmude2026.calicotab.com",
        year=2026,
        status=TournamentStatus.IN_PROGRESS,
    )
    db_session.add_all(
        [
            Round(
                tournament_id=completed.id,
                seq=1,
                name="Ronda 1",
                stage=RoundStage.PRELIMINARY,
                status=RoundStatus.COMPLETED,
                motion_text="EC prohibiría X",
                motion_category=MotionCategory.POLICY,
            ),
            # Same round shape on a tournament that's still live -- must NOT leak, both because
            # it isn't archived yet and because motion_category is settlement ground truth.
            Round(
                tournament_id=in_progress.id,
                seq=1,
                name="Ronda 1",
                stage=RoundStage.PRELIMINARY,
                status=RoundStatus.COMPLETED,
                motion_text="EC apoyaría Y",
                motion_category=MotionCategory.SUPPORT_OPPOSE,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/v1/motions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["tournament_name"] == "CMUDE 2024"
    assert body[0]["motion_category"] == "policy"


async def test_motions_filters_by_category_and_year(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    t2024 = await _make_tournament(db_session, name="CMUDE 2024", slug="cmude-2024", year=2024)
    t2023 = await _make_tournament(
        db_session,
        name="CMUDE 2023",
        slug="cmude-2023",
        source_base_url="https://cmude2023.calicotab.com",
        year=2023,
    )
    db_session.add_all(
        [
            Round(
                tournament_id=t2024.id,
                seq=1,
                name="Ronda 1",
                stage=RoundStage.PRELIMINARY,
                status=RoundStatus.COMPLETED,
                motion_text="EC prohibiría X",
                motion_category=MotionCategory.POLICY,
            ),
            Round(
                tournament_id=t2023.id,
                seq=1,
                name="Ronda 1",
                stage=RoundStage.PRELIMINARY,
                status=RoundStatus.COMPLETED,
                motion_text="EC apoyaría Y",
                motion_category=MotionCategory.SUPPORT_OPPOSE,
            ),
        ]
    )
    await db_session.commit()

    by_category = await client.get("/api/v1/motions", params={"category": "policy"})
    assert [m["tournament_name"] for m in by_category.json()] == ["CMUDE 2024"]

    by_year = await client.get("/api/v1/motions", params={"year": 2023})
    assert [m["tournament_name"] for m in by_year.json()] == ["CMUDE 2023"]
