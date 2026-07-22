"""Pure data-transfer objects produced by the scraper package.

Nothing here imports SQLAlchemy or touches the database -- the ingestion service (app/services)
is the only thing that knows how to turn these into ORM rows. This is what keeps the scraper
100% swappable: tomorrow's "CalicoTab v2" or an entirely different tab system just needs to
produce the same DTOs, and every downstream service keeps working unmodified.

Reusing `app.models.enums` here (BPPosition, SpeakerRole, JudgeRole) is a deliberate, narrow
exception to that decoupling: those are plain ``enum.Enum`` subclasses with zero SQLAlchemy/DB
dependency, so importing them doesn't create an ORM coupling -- it just avoids maintaining two
copies of "PM/DPM/LO/DLO/..." in the codebase.
"""

from dataclasses import dataclass, field

from app.models.enums import BPPosition, JudgeRole, SpeakerRole


@dataclass(frozen=True)
class ScrapedInstitution:
    code: str
    name: str
    region: str | None = None


@dataclass(frozen=True)
class ScrapedAdjudicator:
    external_id: int
    name: str
    institution_code: str | None
    is_independent: bool
    broke: bool = False


@dataclass(frozen=True)
class ScrapedTeam:
    external_id: int
    name: str
    emoji: str | None
    category_names: tuple[str, ...] = ()
    speaker_names: tuple[str, ...] = ()
    # Informational cross-check aggregates as published by CalicoTab's Team Tab. The
    # authoritative per-debate detail used to populate DebateTeam/SpeakerScore comes from the
    # round results pages instead -- these are only used by the ingestion service to sanity
    # check its own computed ranking against what the site itself displays.
    points: int | None = None
    speaker_total: float | None = None


@dataclass(frozen=True)
class ScrapedSpeaker:
    name: str
    team_external_id: int
    category_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScrapedRoundRef:
    """A round as discovered from the site-wide results navigation menu -- present even for
    rounds that haven't been drawn/played yet, which is how we learn the tournament's full
    round list without needing an admin-only schedule page."""

    seq: int
    name: str
    is_elimination: bool


@dataclass(frozen=True)
class ScrapedDebateAdjudicator:
    external_id: int
    name: str
    role: JudgeRole


@dataclass(frozen=True)
class ScrapedDebateTeamEntry:
    team_external_id: int
    team_name: str
    position: BPPosition
    rank_in_debate: int | None
    result_label: str | None = None
    # Elimination-round rows use "Advancing"/"Eliminated" instead of a 1st-4th rank (see
    # `ScrapedDebate` docstring) -- None for preliminary rounds, which don't have this concept.
    advanced: bool | None = None


@dataclass(frozen=True)
class ScrapedDebate:
    """One debate within a round, reconstructed by grouping the round-results table's rows
    (one row per team) by the shared ballot/debate external id.

    Preliminary rounds always have a per-row ballot link, which is what we group by AND what
    becomes ``debate_external_id``. Elimination rounds published without public ballots have
    no such link -- CalicoTab's row instead reports "Advancing"/"Eliminated" (see `advanced`
    above) and lists the debate's full team composition in prose, which we use to synthesize a
    stable pseudo external id instead (see `_synthetic_debate_id` in parsers.py). Either way,
    this DTO's shape doesn't change -- only where `debate_external_id` came from.
    """

    debate_external_id: int
    round_seq: int
    teams: tuple[ScrapedDebateTeamEntry, ...]
    adjudicators: tuple[ScrapedDebateAdjudicator, ...] = ()
    ballot_source_url: str | None = None


@dataclass(frozen=True)
class ScrapedSpeakerScore:
    team_name: str
    role: SpeakerRole
    speaker_name: str
    score: float | None
    is_iron: bool = False


@dataclass(frozen=True)
class ScrapedBallotTeamBlock:
    team_name: str
    position: BPPosition
    total_score: float | None
    speaker_scores: tuple[ScrapedSpeakerScore, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ScrapedBallot:
    debate_external_id: int
    room_name: str | None
    round_label: str | None
    motion_text: str | None
    teams: tuple[ScrapedBallotTeamBlock, ...]


@dataclass(frozen=True)
class ScrapedDrawTeamEntry:
    team_external_id: int
    team_name: str
    position: BPPosition


@dataclass(frozen=True)
class ScrapedDrawDebate:
    room_name: str | None
    teams: tuple[ScrapedDrawTeamEntry, ...]


@dataclass(frozen=True)
class ScrapedDraw:
    """The public draw page for the round currently in progress. This is the only public
    signal of which round is ACTIVE: the results navigation only ever lists rounds whose
    results page already exists, so a round that has been drawn but not yet judged (the one
    everyone is actually debating right now) is invisible to the rest of the scrape."""

    round_name: str
    debates: tuple[ScrapedDrawDebate, ...]


@dataclass(frozen=True)
class ScrapedBreakCategoryRef:
    slug: str
    name: str
    is_adjudicator_break: bool


@dataclass(frozen=True)
class ScrapedTeamBreakEntry:
    team_external_id: int | None
    team_name: str
    rank: int | None


@dataclass(frozen=True)
class TournamentSnapshot:
    """Everything the orchestrator gathered in one scrape cycle. Kept flat and serializable
    so it can be logged, cached, or unit-tested without touching a database.

    ``adjudicators`` is the single authoritative adjudicator list (from the participants page)
    with ``broke`` set to True for anyone who also appears on the break/adjudicators page --
    there's no separate "adjudicator break" collection, since it's the same entities, just
    flagged, rather than a distinct kind of record like a team break (which does carry its own
    rank).
    """

    institutions: tuple[ScrapedInstitution, ...] = ()
    adjudicators: tuple[ScrapedAdjudicator, ...] = ()
    teams: tuple[ScrapedTeam, ...] = ()
    speakers: tuple[ScrapedSpeaker, ...] = ()
    rounds: tuple[ScrapedRoundRef, ...] = ()
    debates_by_round: dict[int, tuple[ScrapedDebate, ...]] = field(default_factory=dict)
    draw: "ScrapedDraw | None" = None
    ballots: tuple[ScrapedBallot, ...] = ()
    break_categories: tuple[ScrapedBreakCategoryRef, ...] = ()
    team_breaks: dict[str, tuple[ScrapedTeamBreakEntry, ...]] = field(default_factory=dict)
