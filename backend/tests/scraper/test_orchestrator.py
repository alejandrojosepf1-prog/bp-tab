import pytest

from app.scraper.client import CalicoTabClient
from app.scraper.orchestrator import TournamentScraper
from app.scraper.parsers import parse_round_results

BASE_URL = "https://fake.calicotab.com"
SLUG = "open"

# Rounds 2-8, 10-13 aren't backed by a fixture; the orchestrator must treat their 403 as
# "not published yet" and simply skip them rather than failing the whole scrape.
_UNAVAILABLE_ROUNDS = [2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13]


def _known_debate_ids_except(fixture_html, *, keep_unknown: int) -> frozenset[int]:
    all_ids = set()
    for name, seq in [("round_results_1.html", 1), ("round_results_9.html", 9)]:
        for debate in parse_round_results(fixture_html(name), round_seq=seq):
            all_ids.add(debate.debate_external_id)
    all_ids.discard(keep_unknown)
    return frozenset(all_ids)


@pytest.mark.asyncio
async def test_full_scrape_cycle_against_real_fixtures(httpx_mock, fixture_html) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/open/participants/institutions/",
        text=fixture_html("institutions_list.html"),
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/open/participants/list/", text=fixture_html("participants_list.html")
    )
    httpx_mock.add_response(url=f"{BASE_URL}/open/tab/team/", text=fixture_html("team_tab.html"))
    httpx_mock.add_response(
        url=f"{BASE_URL}/open/tab/speaker/", text=fixture_html("speaker_tab.html")
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/open/results/round/1/", text=fixture_html("round_results_1.html")
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/open/results/round/9/", text=fixture_html("round_results_9.html")
    )
    for seq in _UNAVAILABLE_ROUNDS:
        httpx_mock.add_response(url=f"{BASE_URL}/open/results/round/{seq}/", status_code=403)
    httpx_mock.add_response(
        url=f"{BASE_URL}/open/results/debate/443236/scoresheets/",
        text=fixture_html("ballot_443236.html"),
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/open/break/adjudicators/", text=fixture_html("break_adjudicators.html")
    )
    # No public draw up right now (between rounds) -- the orchestrator must treat it as
    # "no active round" and continue, exactly like an unavailable results page.
    httpx_mock.add_response(url=f"{BASE_URL}/open/draw/", status_code=403)
    httpx_mock.add_response(url=f"{BASE_URL}/open/motions/", text=fixture_html("motions.html"))

    known_ids = _known_debate_ids_except(fixture_html, keep_unknown=443236)

    client = CalicoTabClient(BASE_URL, min_delay_seconds=0)
    scraper = TournamentScraper(BASE_URL, SLUG, client=client)
    try:
        snapshot = await scraper.scrape(known_debate_external_ids=known_ids)
    finally:
        await scraper.close()

    assert len(snapshot.institutions) == 62
    assert len(snapshot.adjudicators) == 140
    assert sum(1 for a in snapshot.adjudicators if a.broke) == 48
    assert len(snapshot.teams) == 146
    assert len(snapshot.speakers) == 292
    assert len(snapshot.rounds) == 13

    # Only the two rounds with a mocked (non-403) response should be present.
    assert set(snapshot.debates_by_round.keys()) == {1, 9}
    assert len(snapshot.debates_by_round[1]) == 35
    assert len(snapshot.debates_by_round[9]) == 35

    # Only the one debate NOT in known_debate_external_ids should have had its ballot fetched.
    assert len(snapshot.ballots) == 1
    assert snapshot.ballots[0].debate_external_id == 443236

    assert len(snapshot.break_categories) == 1
    assert snapshot.break_categories[0].is_adjudicator_break is True
    assert snapshot.team_breaks == {}
