"""Full pipeline integration test: HTTP-mocked real CMUDE fixtures -> scrape -> ingest ->
tournament status refresh -> break predictions -> bet settlement, all in one task call.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.models import (
    BreakCategory,
    BreakPrediction,
    ScrapeLog,
    Team,
    TeamBreakCategory,
    Tournament,
    User,
)
from app.models.betting import BetMarket, Prediction
from app.models.enums import (
    BetMarketStatus,
    BetType,
    ScrapeStatus,
    TournamentStatus,
    UserRole,
)
from app.tasks.scrape_tasks import scrape_all_active_tournaments_async, scrape_tournament_async

FIXTURES_DIR = Path(__file__).parent.parent / "scraper" / "fixtures"
BASE_URL = "https://fake.calicotab.com"
_UNAVAILABLE_ROUNDS = [2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13]


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _mock_cmude_tournament(httpx_mock) -> None:
    """Registers every page a scrape cycle can request, all reusable, so this can be called
    once and satisfy any number of scrape cycles within a single test (the orchestrator
    re-fetches institutions/participants/tabs/round-results every cycle regardless of whether
    anything changed -- only ballots are skipped once a debate is already known)."""
    pages = {
        f"{BASE_URL}/api/v1/tournaments/open/": (404, None),
        f"{BASE_URL}/open/participants/institutions/": (200, "institutions_list.html"),
        f"{BASE_URL}/open/participants/list/": (200, "participants_list.html"),
        f"{BASE_URL}/open/tab/team/": (200, "team_tab.html"),
        f"{BASE_URL}/open/tab/speaker/": (200, "speaker_tab.html"),
        f"{BASE_URL}/open/results/round/1/": (200, "round_results_1.html"),
        f"{BASE_URL}/open/results/round/9/": (200, "round_results_9.html"),
        f"{BASE_URL}/open/results/debate/443236/scoresheets/": (200, "ballot_443236.html"),
        f"{BASE_URL}/open/break/adjudicators/": (200, "break_adjudicators.html"),
        # No public draw between rounds -> scraper skips active-round ingestion.
        f"{BASE_URL}/open/draw/": (403, None),
        f"{BASE_URL}/open/motions/": (200, "motions.html"),
    }
    for url, (status_code, fixture_name) in pages.items():
        text = _fixture(fixture_name) if fixture_name else None
        httpx_mock.add_response(url=url, status_code=status_code, text=text, is_reusable=True)
    for seq in _UNAVAILABLE_ROUNDS:
        httpx_mock.add_response(
            url=f"{BASE_URL}/open/results/round/{seq}/", status_code=403, is_reusable=True
        )
    # Round 1 and 9 together have 70 debates; a fresh (never-before-scraped) tournament has no
    # `known_debate_external_ids` yet, so the orchestrator tries every one of their ballots. We
    # only ship a real fixture for 443236 -- everything else is a fallback "not published" 403,
    # exactly like the rounds this tournament hasn't reached its ballot-release for yet.
    #
    # Scoped to the ballot URL *pattern* specifically (rather than a bare no-criteria catch-all)
    # so it never becomes a second candidate match for the exact-URL page mocks above: pytest-
    # httpx's reuse rule only re-serves the LAST-registered matcher among several that match the
    # same request once all of them have been used once, so an unscoped catch-all registered
    # after those page mocks would silently steal their slot on a second scrape cycle.
    httpx_mock.add_response(
        url=re.compile(re.escape(BASE_URL) + r"/open/results/debate/\d+/scoresheets/"),
        status_code=403,
        is_reusable=True,
    )


@pytest.mark.asyncio
async def test_scrape_tournament_async_runs_the_full_pipeline(
    httpx_mock, file_db_session_factory
) -> None:
    _mock_cmude_tournament(httpx_mock)

    async with file_db_session_factory() as setup_session:
        tournament = Tournament(
            name="CMUDE 2025",
            slug="cmude2025-open",
            source_base_url=BASE_URL,
            source_slug="open",
            status=TournamentStatus.UPCOMING,
        )
        setup_session.add(tournament)
        await setup_session.flush()

        open_category = BreakCategory(
            tournament_id=tournament.id, name="Open", slug="open", break_size=2
        )
        setup_session.add(open_category)
        await setup_session.commit()
        tournament_id = tournament.id
        category_id = open_category.id

    result = await scrape_tournament_async(tournament_id, session_factory=file_db_session_factory)

    assert result["tournament_id"] == tournament_id
    assert result["entities_created"] > 0

    async with file_db_session_factory() as verify_session:
        tournament = await verify_session.get(Tournament, tournament_id)
        # Round 9 (the latest with results) is preliminary; rounds 10-13 (eliminations) are only
        # scheduled, not judged, so the tournament should read as still IN_PROGRESS.
        assert tournament.status == TournamentStatus.IN_PROGRESS
        assert tournament.api_available is False  # the mocked /api/v1/tournaments/open/ 404'd

        teams = (
            (await verify_session.execute(select(Team).where(Team.tournament_id == tournament_id)))
            .scalars()
            .all()
        )
        assert len(teams) == 146

        # This test pre-creates a BreakCategory(slug="open") before scraping specifically to
        # exercise ingestion's general-break backfill (see
        # ingestion.py::_ensure_general_break_category): since no real tournament reliably tags
        # teams into an implicit "Open" category, ingestion links EVERY scraped team to it
        # (idempotently -- the pre-existing "open" row is reused, not duplicated). With
        # break_size already set (2, from setup above) and all 146 teams now linked, the
        # break predictor has real standings to assess and should produce predictions.
        linked = (
            (
                await verify_session.execute(
                    select(TeamBreakCategory).where(
                        TeamBreakCategory.break_category_id == category_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(linked) == 146
        predictions = (await verify_session.execute(select(BreakPrediction))).scalars().all()
        assert len(predictions) > 0


@pytest.mark.asyncio
async def test_scrape_tournament_async_settles_a_champion_market_once_resolvable(
    httpx_mock, file_db_session_factory
) -> None:
    _mock_cmude_tournament(httpx_mock)

    async with file_db_session_factory() as setup_session:
        tournament = Tournament(
            name="CMUDE 2025",
            slug="cmude2025-open",
            source_base_url=BASE_URL,
            source_slug="open",
            status=TournamentStatus.UPCOMING,
        )
        setup_session.add(tournament)
        await setup_session.commit()
        tournament_id = tournament.id

    await scrape_tournament_async(tournament_id, session_factory=file_db_session_factory)

    async with file_db_session_factory() as session:
        pucp_fm = (
            await session.execute(
                select(Team).where(Team.tournament_id == tournament_id, Team.external_id == 259867)
            )
        ).scalar_one()

        market = BetMarket(
            tournament_id=tournament_id,
            bet_type=BetType.CHAMPION,
            label="Champion?",
            opens_at=datetime.now(timezone.utc),
            closes_at=datetime.now(timezone.utc),
            points_rule={},
        )
        session.add(market)
        await session.flush()

        user = User(email="a@example.com", password_hash="x", display_name="A", role=UserRole.USER)
        session.add(user)
        await session.flush()
        session.add(
            Prediction(
                bet_market_id=market.id,
                user_id=user.id,
                entity_key="__market__",
                payload={"team_id": pucp_fm.id},
                locked_at=datetime.now(timezone.utc),
                stake_amount=10.0,
                odds=10.0,
            )
        )
        await session.commit()

        tournament = await session.get(Tournament, tournament_id)
        tournament.champion_team_id = pucp_fm.id
        await session.commit()

    # A second scrape cycle should notice the market is now resolvable and settle it.
    await scrape_tournament_async(tournament_id, session_factory=file_db_session_factory)

    async with file_db_session_factory() as session:
        market = (
            await session.execute(select(BetMarket).where(BetMarket.tournament_id == tournament_id))
        ).scalar_one()
        assert market.status == BetMarketStatus.SETTLED
        prediction = (await session.execute(select(Prediction))).scalar_one()
        # Pieza 3: pari-mutuel payout against the real CMUDE fixture's final standings, not
        # stake(10) * frozen odds(10) -- `odds` is only the placement-time projection now.
        assert prediction.points_awarded == pytest.approx(137.8)


@pytest.mark.asyncio
async def test_scrape_all_active_tournaments_async_lists_only_active(
    file_db_session_factory,
) -> None:
    async with file_db_session_factory() as session:
        active = Tournament(
            name="Active",
            slug="active",
            source_base_url=BASE_URL,
            source_slug="open",
            is_active=True,
        )
        inactive = Tournament(
            name="Inactive",
            slug="inactive",
            source_base_url=BASE_URL,
            source_slug="masters",
            is_active=False,
        )
        session.add_all([active, inactive])
        await session.commit()
        active_id = active.id

    ids = await scrape_all_active_tournaments_async(session_factory=file_db_session_factory)
    assert ids == [active_id]


@pytest.mark.asyncio
async def test_scrape_tournament_async_records_a_failed_scrape_log_on_error(
    httpx_mock, file_db_session_factory
) -> None:
    """Regression guard: a scrape/ingest exception used to vanish with no trace at all -- the
    admin 'Scraping' screen only ever reads ScrapeLog, and the only place that ever wrote one was
    the happy path at the very end of IngestionService.ingest. Now a failure lands in that same
    table instead of only Render's raw log stream."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/tournaments/open/", status_code=404, is_reusable=True
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/open/participants/institutions/",
        status_code=200,
        text=_fixture("institutions_list.html"),
        is_reusable=True,
    )
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url=f"{BASE_URL}/open/participants/list/",
        is_reusable=True,  # the client retries via tenacity -- every attempt must see the error
    )

    async with file_db_session_factory() as setup_session:
        tournament = Tournament(
            name="CMUDE 2025", slug="cmude2025-open", source_base_url=BASE_URL,
            source_slug="open", status=TournamentStatus.UPCOMING,
        )
        setup_session.add(tournament)
        await setup_session.commit()
        tournament_id = tournament.id

    with pytest.raises(httpx.ConnectError):
        await scrape_tournament_async(tournament_id, session_factory=file_db_session_factory)

    async with file_db_session_factory() as verify_session:
        log = (
            await verify_session.execute(
                select(ScrapeLog).where(ScrapeLog.tournament_id == tournament_id)
            )
        ).scalar_one()
        assert log.status == ScrapeStatus.FAILED
        assert "connection refused" in log.error_message
