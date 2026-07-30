"""Coordinates one full scrape cycle for a single tournament.

Fetch order matters for efficiency, not correctness: institutions and the participants list
change rarely once a tournament starts, so they're cheap to re-fetch every cycle; round
results are re-fetched every cycle since that's exactly where new information appears; ballots
are the expensive, numerous pages, so we only fetch ones the caller doesn't already have
(``known_debate_external_ids``) -- this is the idempotency guarantee at the scraper's own
level, on top of the upsert-based idempotency the ingestion service applies when writing rows.
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

from app.scraper import parsers
from app.scraper.api_source import probe_api_availability
from app.scraper.client import CalicoTabClient
from app.scraper.dtos import (
    ScrapedAdjudicator,
    ScrapedBallot,
    ScrapedBreakCategoryRef,
    ScrapedDebate,
    ScrapedInstitution,
    ScrapedRoundRef,
    ScrapedSpeaker,
    ScrapedTeam,
    ScrapedTeamBreakEntry,
    TournamentSnapshot,
)
from app.scraper.exceptions import PageNotAvailableError, ParseError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TournamentScraper:
    def __init__(
        self,
        base_url: str,
        tournament_slug: str,
        *,
        client: CalicoTabClient | None = None,
    ) -> None:
        self.tournament_slug = tournament_slug.strip("/")
        self._client = client or CalicoTabClient(base_url)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    def _path(self, suffix: str) -> str:
        return f"/{self.tournament_slug}/{suffix.lstrip('/')}"

    async def check_api_available(self) -> bool:
        return await probe_api_availability(self._client, self.tournament_slug)

    async def scrape(
        self, *, known_debate_external_ids: frozenset[int] = frozenset()
    ) -> TournamentSnapshot:
        institutions: list[ScrapedInstitution] = await self._safe_fetch_parse(
            "participants/institutions/", parsers.parse_institutions, default=[]
        )

        participants_html = await self._client.get_text(self._path("participants/list/"))
        adjudicators = list(parsers.parse_adjudicators(participants_html))
        rounds = parsers.parse_round_nav(participants_html)
        break_categories = parsers.parse_break_category_nav(participants_html)

        teams = await self._fetch_teams(participants_html)
        speakers = await self._fetch_speakers(participants_html)

        debates_by_round, all_debates = await self._fetch_round_results(rounds)

        # The round currently in progress only exists on the public draw page -- the results
        # nav above never lists it until its results page appears (see ScrapedDraw docstring).
        draw = await self._safe_fetch_parse("draw/", parsers.parse_draw, default=None)

        ballots = await self._fetch_new_ballots(all_debates, known_debate_external_ids)

        adjudicators = await self._apply_adjudicator_break(adjudicators, break_categories)
        team_breaks = await self._fetch_team_breaks(break_categories)

        # One cheap page holding every round's motion + info slide. Fetched every cycle (not
        # just once) because a round's motion is published only when that round is released --
        # an out-round sits there with an empty motion until then.
        motions = await self._safe_fetch_parse("motions/", parsers.parse_motions, default=[])

        return TournamentSnapshot(
            institutions=tuple(institutions),
            adjudicators=tuple(adjudicators),
            teams=tuple(teams),
            speakers=tuple(speakers),
            rounds=tuple(rounds),
            debates_by_round=debates_by_round,
            draw=draw,
            ballots=tuple(ballots),
            break_categories=tuple(break_categories),
            team_breaks=team_breaks,
            motions=tuple(motions),
        )

    async def _safe_fetch_parse(self, path: str, parse_fn: Callable[[str], T], *, default: T) -> T:
        try:
            html = await self._client.get_text(self._path(path))
        except PageNotAvailableError:
            logger.info("page not yet available: %s", path)
            return default
        try:
            return parse_fn(html)
        except ParseError:
            logger.exception("failed to parse %s", path)
            return default

    async def _fetch_teams(self, participants_html: str) -> list[ScrapedTeam]:
        try:
            html = await self._client.get_text(self._path("tab/team/"))
            return list(parsers.parse_team_tab(html))
        except PageNotAvailableError:
            logger.info("team tab not yet available, falling back to participants list")
            return list(parsers.parse_participants_teams(participants_html))

    async def _fetch_speakers(self, participants_html: str) -> list[ScrapedSpeaker]:
        try:
            html = await self._client.get_text(self._path("tab/speaker/"))
            return list(parsers.parse_speakers(html))
        except PageNotAvailableError:
            logger.info("speaker tab not yet available, falling back to participants list")
            idx = parsers.find_speaker_table_index(participants_html)
            return list(parsers.parse_speakers(participants_html, table_index=idx))

    async def _fetch_round_results(
        self, rounds: list[ScrapedRoundRef]
    ) -> tuple[dict[int, tuple[ScrapedDebate, ...]], list[ScrapedDebate]]:
        debates_by_round: dict[int, tuple[ScrapedDebate, ...]] = {}
        all_debates: list[ScrapedDebate] = []
        for r in rounds:
            try:
                html = await self._client.get_text(self._path(f"results/round/{r.seq}/"))
            except PageNotAvailableError:
                continue
            try:
                debates = parsers.parse_round_results(html, round_seq=r.seq)
            except ParseError:
                logger.exception("failed to parse round %s results", r.seq)
                continue
            debates_by_round[r.seq] = tuple(debates)
            all_debates.extend(debates)
        return debates_by_round, all_debates

    async def _fetch_new_ballots(
        self, debates: list[ScrapedDebate], known_debate_external_ids: frozenset[int]
    ) -> list[ScrapedBallot]:
        ballots = []
        for debate in debates:
            if (
                debate.debate_external_id in known_debate_external_ids
                or not debate.ballot_source_url
            ):
                continue
            try:
                html = await self._client.get_text(debate.ballot_source_url)
            except PageNotAvailableError:
                continue
            try:
                ballots.append(parsers.parse_ballot(html, debate.debate_external_id))
            except ParseError:
                logger.exception("failed to parse ballot for debate %s", debate.debate_external_id)
        return ballots

    async def _apply_adjudicator_break(
        self,
        adjudicators: list[ScrapedAdjudicator],
        break_categories: list[ScrapedBreakCategoryRef],
    ) -> list[ScrapedAdjudicator]:
        adj_category = next((c for c in break_categories if c.is_adjudicator_break), None)
        if adj_category is None:
            return adjudicators
        try:
            html = await self._client.get_text(self._path(f"break/{adj_category.slug}/"))
        except PageNotAvailableError:
            return adjudicators
        broken_ids = {a.external_id for a in parsers.parse_adjudicators(html, broke=True)}
        return [
            (a if a.external_id not in broken_ids else replace(a, broke=True)) for a in adjudicators
        ]

    async def _fetch_team_breaks(
        self, break_categories: list[ScrapedBreakCategoryRef]
    ) -> dict[str, tuple[ScrapedTeamBreakEntry, ...]]:
        team_breaks: dict[str, tuple[ScrapedTeamBreakEntry, ...]] = {}
        for category in break_categories:
            if category.is_adjudicator_break:
                continue
            try:
                html = await self._client.get_text(self._path(f"break/{category.slug}/"))
            except PageNotAvailableError:
                continue
            try:
                team_breaks[category.slug] = tuple(parsers.parse_team_break(html))
            except ParseError:
                logger.exception("failed to parse team break for category %s", category.slug)
        return team_breaks
