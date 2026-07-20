"""Turns one scraper TournamentSnapshot into upserted rows, tracking every change made.

Processing order matters here (it mirrors the schema's foreign keys): institutions before
teams/adjudicators that reference them, teams before speakers, rounds before debates, debates
before debate_teams, debate_teams before speaker_scores. Every write goes through
`upsert_by_natural_key`, so re-ingesting an unchanged snapshot is a true no-op -- nothing is
duplicated and no spurious ChangeEvent rows are produced.

Institution linkage for teams is a best-effort heuristic (documented on `_match_institution`):
CalicoTab does not publish a team -> institution link anywhere public for this circuit's
tournaments, but team names conventionally start with their institution's short code (e.g.
"PUCP FM"), so we match on that prefix when possible and simply leave it unset otherwise.
"""

import datetime
import logging
import re
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ranking import team_points_for_rank
from app.models import (
    Adjudicator,
    AdjudicatorBreak,
    Break,
    BreakCategory,
    ChangeEvent,
    Debate,
    DebateAdjudicator,
    DebateTeam,
    Institution,
    Result,
    Room,
    Round,
    ScrapeLog,
    Speaker,
    SpeakerCategory,
    SpeakerCategoryLink,
    SpeakerScore,
    Team,
    TeamBreakCategory,
    Tournament,
)
from app.models.enums import (
    BreakStatus,
    ChangeType,
    RoundStage,
    RoundStatus,
    ScrapeStatus,
    ScrapeStrategy,
)
from app.repositories.upsert import UpsertResult, upsert_by_natural_key
from app.scraper.dtos import TournamentSnapshot

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "category"


@dataclass
class IngestionSummary:
    entities_created: int = 0
    entities_updated: int = 0
    new_debate_external_ids: list[int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.new_debate_external_ids is None:
            self.new_debate_external_ids = []


class IngestionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._summary = IngestionSummary()

    async def ingest(self, tournament: Tournament, snapshot: TournamentSnapshot) -> ScrapeLog:
        started_at = datetime.datetime.now(datetime.timezone.utc)
        self._summary = IngestionSummary()

        # Bulk cold-start ingestion against a remote/pooled Postgres can run for many minutes
        # (each entity upsert is its own SELECT-then-write round trip -- see upsert.py), with no
        # externally-visible signal otherwise. These phase markers are the difference between
        # "still working" and "hung" when watching a live log.
        logger.info("ingest: institutions (%d)", len(snapshot.institutions))
        institution_id_by_code = await self._ingest_institutions(tournament, snapshot)
        logger.info("ingest: adjudicators (%d)", len(snapshot.adjudicators))
        adjudicator_id_by_ext = await self._ingest_adjudicators(
            tournament, snapshot, institution_id_by_code
        )
        logger.info("ingest: teams (%d)", len(snapshot.teams))
        team_id_by_ext = await self._ingest_teams(tournament, snapshot, institution_id_by_code)
        logger.info("ingest: speakers (%d)", len(snapshot.speakers))
        speaker_id_by_key = await self._ingest_speakers(tournament, snapshot, team_id_by_ext)
        logger.info("ingest: rounds (%d)", len(snapshot.rounds))
        round_id_by_seq = await self._ingest_rounds(tournament, snapshot)
        total_debates = sum(len(d) for d in snapshot.debates_by_round.values())
        logger.info("ingest: debates (%d)", total_debates)
        new_debate_ids = await self._ingest_debates(
            tournament, snapshot, team_id_by_ext, adjudicator_id_by_ext, round_id_by_seq
        )
        logger.info("ingest: ballots (%d)", len(snapshot.ballots))
        await self._ingest_ballots(tournament, snapshot, team_id_by_ext, speaker_id_by_key)
        logger.info("ingest: breaks")
        await self._ingest_breaks(tournament, snapshot, team_id_by_ext, adjudicator_id_by_ext)
        logger.info("ingest: done, committing")

        self._summary.new_debate_external_ids = new_debate_ids

        log = ScrapeLog(
            tournament_id=tournament.id,
            started_at=started_at,
            finished_at=datetime.datetime.now(datetime.timezone.utc),
            status=ScrapeStatus.SUCCESS,
            strategy_used=ScrapeStrategy.HTML_VUEDATA,
            pages_fetched=0,
            entities_created=self._summary.entities_created,
            entities_updated=self._summary.entities_updated,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def _track(
        self,
        tournament_id: int,
        entity_type: str,
        result: UpsertResult,
        *,
        round_id: int | None = None,
    ) -> None:
        if result.created:
            self._summary.entities_created += 1
        elif result.changed_fields:
            self._summary.entities_updated += 1
        else:
            return
        self.session.add(
            ChangeEvent(
                tournament_id=tournament_id,
                entity_type=entity_type,
                entity_id=result.instance.id,
                change_type=ChangeType.CREATED if result.created else ChangeType.UPDATED,
                field_diff=result.changed_fields,
                round_id=round_id,
                detected_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )

    async def _ingest_institutions(
        self, tournament: Tournament, snapshot: TournamentSnapshot
    ) -> dict[str, int]:
        ids: dict[str, int] = {}
        for inst in snapshot.institutions:
            result = await upsert_by_natural_key(
                self.session,
                Institution,
                lookup={"tournament_id": tournament.id, "code": inst.code},
                values={"name": inst.name, "region": inst.region},
            )
            await self._track(tournament.id, "Institution", result)
            ids[inst.code] = result.instance.id
        return ids

    async def _ingest_adjudicators(
        self,
        tournament: Tournament,
        snapshot: TournamentSnapshot,
        institution_id_by_code: dict[str, int],
    ) -> dict[int, int]:
        ids: dict[int, int] = {}
        for adj in snapshot.adjudicators:
            institution_id = (
                institution_id_by_code.get(adj.institution_code) if adj.institution_code else None
            )
            result = await upsert_by_natural_key(
                self.session,
                Adjudicator,
                lookup={"tournament_id": tournament.id, "external_id": adj.external_id},
                values={
                    "name": adj.name,
                    "institution_id": institution_id,
                    "is_independent": adj.is_independent,
                },
            )
            await self._track(tournament.id, "Adjudicator", result)
            ids[adj.external_id] = result.instance.id
            if adj.broke:
                break_result = await upsert_by_natural_key(
                    self.session,
                    AdjudicatorBreak,
                    lookup={"tournament_id": tournament.id, "adjudicator_id": result.instance.id},
                    values={
                        "confirmed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    },
                )
                await self._track(tournament.id, "AdjudicatorBreak", break_result)
        return ids

    async def _ingest_teams(
        self,
        tournament: Tournament,
        snapshot: TournamentSnapshot,
        institution_id_by_code: dict[str, int],
    ) -> dict[int, int]:
        ids: dict[int, int] = {}
        for team in snapshot.teams:
            institution_id = _match_institution_by_name_prefix(team.name, institution_id_by_code)
            result = await upsert_by_natural_key(
                self.session,
                Team,
                lookup={"tournament_id": tournament.id, "external_id": team.external_id},
                values={"name": team.name, "emoji": team.emoji, "institution_id": institution_id},
            )
            await self._track(tournament.id, "Team", result)
            ids[team.external_id] = result.instance.id

            for category_name in team.category_names:
                category = await upsert_by_natural_key(
                    self.session,
                    BreakCategory,
                    lookup={"tournament_id": tournament.id, "slug": _slugify(category_name)},
                    values={"name": category_name},
                )
                await self._ensure_link(
                    TeamBreakCategory,
                    team_id=result.instance.id,
                    break_category_id=category.instance.id,
                )
        return ids

    async def _ingest_speakers(
        self, tournament: Tournament, snapshot: TournamentSnapshot, team_id_by_ext: dict[int, int]
    ) -> dict[tuple[int, str], int]:
        ids: dict[tuple[int, str], int] = {}
        for speaker in snapshot.speakers:
            team_id = team_id_by_ext.get(speaker.team_external_id)
            if team_id is None:
                logger.warning(
                    "speaker %s references unknown team_external_id %s",
                    speaker.name,
                    speaker.team_external_id,
                )
                continue
            result = await upsert_by_natural_key(
                self.session,
                Speaker,
                lookup={"tournament_id": tournament.id, "team_id": team_id, "name": speaker.name},
                values={},
            )
            await self._track(tournament.id, "Speaker", result)
            ids[(team_id, speaker.name)] = result.instance.id

            for category_name in speaker.category_names:
                category = await upsert_by_natural_key(
                    self.session,
                    SpeakerCategory,
                    lookup={"tournament_id": tournament.id, "slug": _slugify(category_name)},
                    values={"name": category_name},
                )
                await self._ensure_link(
                    SpeakerCategoryLink,
                    speaker_id=result.instance.id,
                    speaker_category_id=category.instance.id,
                )
        return ids

    async def _ingest_rounds(
        self, tournament: Tournament, snapshot: TournamentSnapshot
    ) -> dict[int, int]:
        ids: dict[int, int] = {}
        for round_ref in snapshot.rounds:
            # `.get(...)` truthiness, not `in`: a round whose results page fetched fine but
            # yielded zero parseable debates must not be marked COMPLETED.
            has_debates = bool(snapshot.debates_by_round.get(round_ref.seq))
            result = await upsert_by_natural_key(
                self.session,
                Round,
                lookup={"tournament_id": tournament.id, "seq": round_ref.seq},
                values={
                    "name": round_ref.name,
                    "stage": RoundStage.ELIMINATION
                    if round_ref.is_elimination
                    else RoundStage.PRELIMINARY,
                    "status": RoundStatus.COMPLETED if has_debates else RoundStatus.DRAFT,
                },
            )
            await self._track(tournament.id, "Round", result)
            ids[round_ref.seq] = result.instance.id
        return ids

    async def _ingest_debates(
        self,
        tournament: Tournament,
        snapshot: TournamentSnapshot,
        team_id_by_ext: dict[int, int],
        adjudicator_id_by_ext: dict[int, int],
        round_id_by_seq: dict[int, int],
    ) -> list[int]:
        new_debate_external_ids: list[int] = []
        total_debates = sum(len(d) for d in snapshot.debates_by_round.values())
        processed = 0
        for round_seq, debates in snapshot.debates_by_round.items():
            round_id = round_id_by_seq.get(round_seq)
            if round_id is None:
                continue
            for debate in debates:
                processed += 1
                if processed % 25 == 0 or processed == total_debates:
                    logger.info("ingest: debates %d/%d", processed, total_debates)
                result = await upsert_by_natural_key(
                    self.session,
                    Debate,
                    lookup={
                        "tournament_id": tournament.id,
                        "external_id": debate.debate_external_id,
                    },
                    values={"round_id": round_id},
                )
                await self._track(tournament.id, "Debate", result, round_id=round_id)
                if result.created:
                    new_debate_external_ids.append(debate.debate_external_id)
                debate_id = result.instance.id

                for team_entry in debate.teams:
                    team_id = team_id_by_ext.get(team_entry.team_external_id)
                    if team_id is None:
                        continue
                    team_points = (
                        team_points_for_rank(team_entry.rank_in_debate)
                        if team_entry.rank_in_debate
                        else None
                    )
                    dt_result = await upsert_by_natural_key(
                        self.session,
                        DebateTeam,
                        lookup={"debate_id": debate_id, "team_id": team_id},
                        values={
                            "position": team_entry.position,
                            "rank_in_debate": team_entry.rank_in_debate,
                            "team_points": team_points,
                            "advanced": team_entry.advanced,
                        },
                    )
                    await self._track(tournament.id, "DebateTeam", dt_result, round_id=round_id)

                for adj_entry in debate.adjudicators:
                    adjudicator_id = adjudicator_id_by_ext.get(adj_entry.external_id)
                    if adjudicator_id is None:
                        continue
                    da_result = await upsert_by_natural_key(
                        self.session,
                        DebateAdjudicator,
                        lookup={"debate_id": debate_id, "adjudicator_id": adjudicator_id},
                        values={"role": adj_entry.role},
                    )
                    await self._track(
                        tournament.id, "DebateAdjudicator", da_result, round_id=round_id
                    )

                if debate.ballot_source_url:
                    result_row = await upsert_by_natural_key(
                        self.session,
                        Result,
                        lookup={"debate_id": debate_id},
                        values={"ballot_source_url": debate.ballot_source_url},
                    )
                    await self._track(tournament.id, "Result", result_row, round_id=round_id)
        return new_debate_external_ids

    async def _ingest_ballots(
        self,
        tournament: Tournament,
        snapshot: TournamentSnapshot,
        team_id_by_ext: dict[int, int],
        speaker_id_by_key: dict[tuple[int, str], int],
    ) -> None:
        total_ballots = len(snapshot.ballots)
        for processed, ballot in enumerate(snapshot.ballots, start=1):
            if processed % 25 == 0 or processed == total_ballots:
                logger.info("ingest: ballots %d/%d", processed, total_ballots)
            debate = (
                await self.session.execute(
                    select(Debate).filter_by(
                        tournament_id=tournament.id, external_id=ballot.debate_external_id
                    )
                )
            ).scalar_one_or_none()
            if debate is None:
                logger.warning(
                    "ballot for unknown debate_external_id %s", ballot.debate_external_id
                )
                continue

            room_id = None
            if ballot.room_name:
                room_result = await upsert_by_natural_key(
                    self.session,
                    Room,
                    lookup={"tournament_id": tournament.id, "name": ballot.room_name},
                    values={},
                )
                await self._track(tournament.id, "Room", room_result)
                room_id = room_result.instance.id

            if room_id is not None and debate.room_id != room_id:
                debate.room_id = room_id
            if ballot.motion_text:
                result_row = await upsert_by_natural_key(
                    self.session,
                    Result,
                    lookup={"debate_id": debate.id},
                    values={"motion_text": ballot.motion_text},
                )
                await self._track(tournament.id, "Result", result_row)

            debate_teams = (
                (await self.session.execute(select(DebateTeam).filter_by(debate_id=debate.id)))
                .scalars()
                .all()
            )
            debate_team_by_position = {dt.position: dt for dt in debate_teams}

            for block in ballot.teams:
                debate_team = debate_team_by_position.get(block.position)
                if debate_team is None:
                    continue
                if (
                    block.total_score is not None
                    and debate_team.speaker_points_total != block.total_score
                ):
                    debate_team.speaker_points_total = block.total_score

                for score in block.speaker_scores:
                    speaker_id = speaker_id_by_key.get((debate_team.team_id, score.speaker_name))
                    if speaker_id is None:
                        logger.warning(
                            "ballot speaker %r not found in roster for team_id %s",
                            score.speaker_name,
                            debate_team.team_id,
                        )
                        continue
                    score_result = await upsert_by_natural_key(
                        self.session,
                        SpeakerScore,
                        lookup={"debate_team_id": debate_team.id, "role": score.role},
                        values={
                            "speaker_id": speaker_id,
                            "score": score.score,
                            "is_iron": score.is_iron,
                        },
                    )
                    await self._track(tournament.id, "SpeakerScore", score_result)

    async def _ingest_breaks(
        self,
        tournament: Tournament,
        snapshot: TournamentSnapshot,
        team_id_by_ext: dict[int, int],
        adjudicator_id_by_ext: dict[int, int],
    ) -> None:
        for slug, entries in snapshot.team_breaks.items():
            category = await upsert_by_natural_key(
                self.session,
                BreakCategory,
                lookup={"tournament_id": tournament.id, "slug": slug},
                values={},
            )
            for entry in entries:
                team_id = (
                    team_id_by_ext.get(entry.team_external_id) if entry.team_external_id else None
                )
                if team_id is None or entry.rank is None:
                    continue
                result = await upsert_by_natural_key(
                    self.session,
                    Break,
                    lookup={
                        "tournament_id": tournament.id,
                        "break_category_id": category.instance.id,
                        "team_id": team_id,
                    },
                    values={"rank": entry.rank, "status": BreakStatus.CONFIRMED},
                )
                await self._track(tournament.id, "Break", result)

    async def _ensure_link(self, model: type, **keys: int) -> None:
        stmt: Select = select(model).filter_by(**keys)
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            self.session.add(model(**keys))
            await self.session.flush()


def _match_institution_by_name_prefix(
    team_name: str, institution_id_by_code: dict[str, int]
) -> int | None:
    """Best-effort heuristic: CalicoTab publishes no team->institution link for this circuit,
    but team names conventionally start with the institution's short code followed by a space
    (e.g. "PUCP FM"). Matches the longest known code that prefixes the team name, so "UNIANDES
    GM" isn't mis-matched by a shorter, unrelated code that happens to also be a prefix."""
    candidates = sorted(institution_id_by_code, key=len, reverse=True)
    for code in candidates:
        if team_name == code or team_name.startswith(code + " "):
            return institution_id_by_code[code]
    return None
