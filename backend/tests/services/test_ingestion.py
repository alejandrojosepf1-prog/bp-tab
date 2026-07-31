"""End-to-end test: real scraper fixtures -> parsers -> DTOs -> IngestionService -> DB rows.

This is the pipeline's most valuable test: it doesn't mock anything between "HTML captured
from the real CMUDE 2025 tab" and "rows in the database", so a break in the contract between
the scraper's DTOs and the ingestion service's expectations shows up here, not in production.
"""

from pathlib import Path

from sqlalchemy import func, select

from app.models import (
    Break,
    ChangeEvent,
    DebateTeam,
    Institution,
    Room,
    SpeakerScore,
    Team,
    Tournament,
)
from app.models.enums import BPPosition, TournamentStatus
from app.scraper import parsers
from app.scraper.dtos import TournamentSnapshot
from app.services.ingestion import IngestionService

FIXTURES_DIR = Path(__file__).parent.parent / "scraper" / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _build_snapshot() -> TournamentSnapshot:
    participants_html = _fixture("participants_list.html")
    idx = parsers.find_speaker_table_index(participants_html)

    debates_r1 = parsers.parse_round_results(_fixture("round_results_1.html"), round_seq=1)
    debates_r9 = parsers.parse_round_results(_fixture("round_results_9.html"), round_seq=9)

    return TournamentSnapshot(
        institutions=tuple(parsers.parse_institutions(_fixture("institutions_list.html"))),
        adjudicators=tuple(parsers.parse_adjudicators(participants_html)),
        teams=tuple(parsers.parse_team_tab(_fixture("team_tab.html"))),
        speakers=tuple(parsers.parse_speakers(participants_html, table_index=idx)),
        rounds=tuple(parsers.parse_round_nav(_fixture("ballot_443236.html"))),
        debates_by_round={1: tuple(debates_r1), 9: tuple(debates_r9)},
        ballots=(parsers.parse_ballot(_fixture("ballot_443236.html"), debate_external_id=443236),),
        break_categories=tuple(parsers.parse_break_category_nav(_fixture("ballot_443236.html"))),
        team_breaks={},
    )


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


async def test_ingest_populates_all_entities_from_real_fixtures(db_session) -> None:
    tournament = await _make_tournament(db_session)
    snapshot = _build_snapshot()

    service = IngestionService(db_session)
    log = await service.ingest(tournament, snapshot)
    await db_session.commit()

    assert log.entities_created > 0

    institution_count = (
        await db_session.execute(
            select(func.count()).select_from(Institution).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()
    assert institution_count == 62

    team_count = (
        await db_session.execute(
            select(func.count()).select_from(Team).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()
    assert team_count == 146

    # Heuristic institution-linkage: "PUCP FM" should resolve to institution code "PUCP".
    pucp_fm = (
        await db_session.execute(
            select(Team).filter_by(tournament_id=tournament.id, external_id=259867)
        )
    ).scalar_one()
    await db_session.refresh(pucp_fm, attribute_names=["institution"])
    assert pucp_fm.institution is not None
    assert pucp_fm.institution.code == "PUCP"

    # Debate 443236 (round 9): 4 DebateTeam rows with correct positions/points, room populated
    # from the ballot, and 8 SpeakerScore rows with correct scores from the scoresheet.
    from app.models import Debate

    debate = (
        await db_session.execute(
            select(Debate).filter_by(tournament_id=tournament.id, external_id=443236)
        )
    ).scalar_one()
    await db_session.refresh(debate, attribute_names=["teams", "room"])
    assert len(debate.teams) == 4
    assert debate.room is not None
    assert "A-233" in debate.room.name

    og_team = next(t for t in debate.teams if t.position == BPPosition.OPENING_GOVERNMENT)
    assert og_team.team_points == 3  # 1st place
    assert og_team.speaker_points_total == 143.0

    speaker_score_count = (
        await db_session.execute(
            select(func.count())
            .select_from(SpeakerScore)
            .join(DebateTeam, SpeakerScore.debate_team_id == DebateTeam.id)
            .filter(DebateTeam.debate_id == debate.id)
        )
    ).scalar_one()
    assert speaker_score_count == 8

    adjudicator_break_count = (
        await db_session.execute(
            select(func.count()).select_from(Break).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()
    # break_adjudicators.html wasn't included in this snapshot's team_breaks (adjudicator breaks
    # go through AdjudicatorBreak, not Break -- Break is team-only), so this should be empty here.
    assert adjudicator_break_count == 0

    room_count = (
        await db_session.execute(
            select(func.count()).select_from(Room).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()
    assert room_count == 1

    change_event_count_first_run = (
        await db_session.execute(
            select(func.count()).select_from(ChangeEvent).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()
    assert change_event_count_first_run > 0


async def test_ingest_is_idempotent_on_a_second_identical_run(db_session) -> None:
    tournament = await _make_tournament(db_session)
    snapshot = _build_snapshot()

    service = IngestionService(db_session)
    await service.ingest(tournament, snapshot)
    await db_session.commit()

    team_count_before = (
        await db_session.execute(
            select(func.count()).select_from(Team).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()
    change_events_before = (
        await db_session.execute(
            select(func.count()).select_from(ChangeEvent).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()

    second_log = await service.ingest(tournament, snapshot)
    await db_session.commit()

    team_count_after = (
        await db_session.execute(
            select(func.count()).select_from(Team).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()
    change_events_after = (
        await db_session.execute(
            select(func.count()).select_from(ChangeEvent).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()

    assert team_count_after == team_count_before  # no duplicates
    assert second_log.entities_created == 0
    assert second_log.entities_updated == 0
    assert change_events_after == change_events_before  # no spurious "changes" on a no-op re-scrape


async def test_ingest_creates_general_open_break_category_when_none_scraped(db_session) -> None:
    """Regression: Tabbycat almost never tags teams with an explicit "Open" category (it's the
    implicit default), so a tournament with no ESL/Novice-style tags used to end up with ZERO
    BreakCategory rows at all -- meaning the admin panel could never offer a team_break market
    for it, even before any real break happened. See ingestion.py's
    _ensure_general_break_category."""
    from app.models import BreakCategory, TeamBreakCategory
    from app.scraper.dtos import ScrapedTeam

    tournament = await _make_tournament(db_session)
    snapshot = TournamentSnapshot(
        teams=(
            ScrapedTeam(external_id=1, name="Team A", emoji=None),
            ScrapedTeam(external_id=2, name="Team B", emoji=None),
        ),
    )

    service = IngestionService(db_session)
    await service.ingest(tournament, snapshot)
    await db_session.commit()

    categories = (
        (
            await db_session.execute(
                select(BreakCategory).filter_by(tournament_id=tournament.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(categories) == 1
    assert categories[0].slug == "open"
    assert categories[0].is_general is True
    assert categories[0].break_size is None  # still needs an admin to set it by hand

    links = (
        (await db_session.execute(select(TeamBreakCategory))).scalars().all()
    )
    assert {link.break_category_id for link in links} == {categories[0].id}
    assert len(links) == 2  # both teams linked to the general category


async def test_ingest_team_break_for_a_never_before_seen_category_does_not_crash(
    db_session,
) -> None:
    """Regression test: the first scrape after a tournament's real break is published sees a
    break-category slug that was never seen via an explicit team tag or the general-category
    backfill (see IngestionService._ingest_breaks docstring) -- e.g. an ESL break, which is
    genuinely new to the DB. This used to write no `name` at all on the freshly-created
    BreakCategory row, tripping the NOT NULL constraint and rolling back the whole scrape cycle."""
    from app.models import Break, BreakCategory
    from app.scraper.dtos import ScrapedBreakCategoryRef, ScrapedTeam, ScrapedTeamBreakEntry

    tournament = await _make_tournament(db_session)
    snapshot = TournamentSnapshot(
        teams=(ScrapedTeam(external_id=1, name="Team A", emoji=None),),
        break_categories=(
            ScrapedBreakCategoryRef(
                slug="esl", name="ESL", is_adjudicator_break=False, path="break/teams/esl/"
            ),
        ),
        team_breaks={"esl": (ScrapedTeamBreakEntry(team_external_id=1, team_name="Team A", rank=1),)},
    )

    service = IngestionService(db_session)
    await service.ingest(tournament, snapshot)
    await db_session.commit()

    category = (
        await db_session.execute(select(BreakCategory).filter_by(tournament_id=tournament.id, slug="esl"))
    ).scalar_one()
    assert category.name == "ESL"

    break_row = (await db_session.execute(select(Break).filter_by(tournament_id=tournament.id))).scalar_one()
    assert break_row.break_category_id == category.id
    assert break_row.rank == 1


async def test_ingest_reingest_of_general_break_category_is_still_a_no_op(db_session) -> None:
    """The general-category backfill must not break idempotency: re-ingesting an unchanged
    snapshot a second time must not produce new ChangeEvent rows or duplicate links."""
    from app.models import ChangeEvent, TeamBreakCategory
    from app.scraper.dtos import ScrapedTeam

    tournament = await _make_tournament(db_session)
    snapshot = TournamentSnapshot(
        teams=(ScrapedTeam(external_id=1, name="Team A", emoji=None),),
    )

    service = IngestionService(db_session)
    await service.ingest(tournament, snapshot)
    await db_session.commit()

    events_before = (
        await db_session.execute(
            select(func.count()).select_from(ChangeEvent).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()

    second_log = await service.ingest(tournament, snapshot)
    await db_session.commit()

    assert second_log.entities_created == 0
    assert second_log.entities_updated == 0

    links = (await db_session.execute(select(TeamBreakCategory))).scalars().all()
    assert len(links) == 1  # not duplicated

    events_after = (
        await db_session.execute(
            select(func.count()).select_from(ChangeEvent).filter_by(tournament_id=tournament.id)
        )
    ).scalar_one()
    assert events_after == events_before  # the backfill produced no spurious changes
