"""Page-type-specific mappers: generic vueData tables / ballot HTML -> typed DTOs.

Every "tab" page (participants, institutions, team tab, speaker tab, round results, break
lists) is parsed through the same `extract_tables_data` + `row_to_dict` machinery in
`vuedata.py` and looked up by column *key*, not position -- this is what lets these parsers
tolerate Tabbycat re-ordering or adding a column without breaking. Only the single ballot/
scoresheet detail page needs BeautifulSoup, since it's plain semantic HTML with no vueData.
"""

import re
import zlib

from bs4 import BeautifulSoup, Tag

from app.models.enums import BPPosition, JudgeRole, SpeakerRole
from app.scraper.dtos import (
    ScrapedAdjudicator,
    ScrapedBallot,
    ScrapedBallotTeamBlock,
    ScrapedBreakCategoryRef,
    ScrapedDebate,
    ScrapedDebateAdjudicator,
    ScrapedDebateTeamEntry,
    ScrapedInstitution,
    ScrapedRoundRef,
    ScrapedSpeaker,
    ScrapedSpeakerScore,
    ScrapedTeam,
    ScrapedTeamBreakEntry,
)
from app.scraper.exceptions import ParseError
from app.scraper.vuedata import (
    cell_emoji,
    cell_external_id,
    cell_sort,
    cell_text,
    external_id_from_link,
    extract_tables_data,
    popover_links,
    row_to_dict,
)

_ELIMINATION_KEYWORDS = (
    "octofinal",
    "octavos",
    "quarterfinal",
    "cuartos",
    "semifinal",
    "final",
)

_POSITION_KEYWORDS = {
    BPPosition.OPENING_GOVERNMENT: ("opening", ("government", "gobierno")),
    BPPosition.OPENING_OPPOSITION: ("opening", ("opposition", "oposici")),
    BPPosition.CLOSING_GOVERNMENT: ("closing", ("government", "gobierno")),
    BPPosition.CLOSING_OPPOSITION: ("closing", ("opposition", "oposici")),
}

_RANK_LABEL_RE = re.compile(r"(\d+)")


def _rows(html: str, table_index: int = 0) -> list[dict]:
    tables = extract_tables_data(html)
    if not tables or table_index >= len(tables):
        raise ParseError(f"expected table index {table_index}, found {len(tables)} table(s)")
    head = tables[table_index]["head"]
    return [row_to_dict(head, row) for row in tables[table_index]["data"]]


def parse_bp_position(label: str) -> BPPosition | None:
    lowered = label.lower()
    for position, (stage_kw, side_kws) in _POSITION_KEYWORDS.items():
        if stage_kw in lowered and any(kw in lowered for kw in side_kws):
            return position
    return None


def parse_rank_from_label(label: str | None) -> int | None:
    if not label:
        return None
    match = _RANK_LABEL_RE.search(label)
    return int(match.group(1)) if match else None


# --- Institutions ---------------------------------------------------------------------


def parse_institutions(html: str) -> list[ScrapedInstitution]:
    out = []
    for row in _rows(html):
        code = cell_text(row.get("code"))
        name = cell_text(row.get("name"))
        if not code or not name:
            continue
        out.append(ScrapedInstitution(code=code, name=name, region=cell_text(row.get("region"))))
    return out


# --- Adjudicators (shared shape: participants list & break/adjudicators pages) ---------


def parse_adjudicators(html: str, *, broke: bool = False) -> list[ScrapedAdjudicator]:
    out = []
    for row in _rows(html):
        name_cell = row.get("name")
        ext_id = cell_external_id(name_cell)
        name = cell_text(name_cell)
        if ext_id is None or not name:
            continue
        institution_code = cell_text(row.get("institution"))
        # These two columns render as a checkmark icon when true and a blank icon when false --
        # `sort` is only a display-ordering hint (and is, confusingly, inverted), not the value.
        independent_cell = row.get("independent") or {}
        is_independent = bool(independent_cell.get("icon"))
        out.append(
            ScrapedAdjudicator(
                external_id=ext_id,
                name=name,
                institution_code=institution_code or None,
                is_independent=is_independent,
                broke=broke,
            )
        )
    return out


# --- Teams (Team Tab) -------------------------------------------------------------------

_ROUND_COL_RE = re.compile(r"^R\d+$")


def parse_team_tab(html: str) -> list[ScrapedTeam]:
    out = []
    for row in _rows(html):
        team_cell = row.get("team")
        ext_id = cell_external_id(team_cell)
        name = cell_text(team_cell)
        if ext_id is None or not name or team_cell is None:
            continue
        categories_text = cell_text(row.get("categories"))
        categories = tuple(c.strip() for c in categories_text.split(",")) if categories_text else ()
        roster_popover = (team_cell.get("popover") or {}).get("content", [])
        speaker_names: tuple[str, ...] = ()
        if roster_popover and "text" in roster_popover[0] and "link" not in roster_popover[0]:
            speaker_names = tuple(
                n.strip() for n in roster_popover[0]["text"].split(",") if n.strip()
            )
        points = cell_sort(row.get("Pts"))
        speaker_total = cell_sort(row.get("Spk"))
        out.append(
            ScrapedTeam(
                external_id=ext_id,
                name=name,
                emoji=cell_emoji(team_cell),
                category_names=categories,
                speaker_names=speaker_names,
                points=int(points) if isinstance(points, int | float) else None,
                speaker_total=float(speaker_total)
                if isinstance(speaker_total, int | float)
                else None,
            )
        )
    return out


# --- Speakers (participants list speaker sub-table, or Speaker Tab) --------------------


def parse_speakers(html: str, *, table_index: int = 0) -> list[ScrapedSpeaker]:
    out = []
    for row in _rows(html, table_index=table_index):
        name = cell_text(row.get("name"))
        team_cell = row.get("team")
        team_ext_id = cell_external_id(team_cell)
        if not name or team_ext_id is None:
            continue
        category_text = cell_text(row.get("category"))
        categories = tuple(c.strip() for c in category_text.split(",")) if category_text else ()
        out.append(
            ScrapedSpeaker(name=name, team_external_id=team_ext_id, category_names=categories)
        )
    return out


def find_speaker_table_index(html: str) -> int:
    """The participants list page has 2 tables (adjudicators, then speakers-by-team); locate
    the speaker one generically by its column signature rather than assuming index 1."""
    for i, table in enumerate(extract_tables_data(html)):
        keys = {col.get("key") for col in table["head"]}
        if {"name", "team"}.issubset(keys):
            return i
    raise ParseError("no speaker table found on participants list page")


def parse_participants_teams(html: str) -> list[ScrapedTeam]:
    """Fallback team discovery for before Round 1 has been drawn, when Team Tab doesn't exist
    yet: derive the team list from the participants page's speaker-by-team sub-table instead.
    Gives name/emoji/roster but not categories or points (those only exist on Team Tab)."""
    idx = find_speaker_table_index(html)
    by_team: dict[int, ScrapedTeam] = {}
    rosters: dict[int, list[str]] = {}
    for row in _rows(html, table_index=idx):
        team_cell = row.get("team")
        ext_id = cell_external_id(team_cell)
        name = cell_text(team_cell)
        speaker_name = cell_text(row.get("name"))
        if ext_id is None or not name:
            continue
        rosters.setdefault(ext_id, [])
        if speaker_name:
            rosters[ext_id].append(speaker_name)
        if ext_id not in by_team:
            by_team[ext_id] = ScrapedTeam(
                external_id=ext_id, name=name, emoji=cell_emoji(team_cell)
            )
    return [
        ScrapedTeam(
            external_id=t.external_id,
            name=t.name,
            emoji=t.emoji,
            speaker_names=tuple(rosters[t.external_id]),
        )
        for t in by_team.values()
    ]


# --- Round results (per-round, one row per team, grouped into debates) ------------------


_ADVANCING_WORDS = ("advanc",)  # matches "advancing"/"advanced" case-insensitively
_ELIMINATED_WORDS = ("eliminat",)  # matches "eliminated"/"eliminating"


def _advanced_from_result_label(label: str | None) -> bool | None:
    if not label:
        return None
    lowered = label.lower()
    if any(w in lowered for w in _ADVANCING_WORDS):
        return True
    if any(w in lowered for w in _ELIMINATED_WORDS):
        return False
    return None


_TEAMS_IN_DEBATE_RE = re.compile(r"^(.*?)\s*\([A-Z]{2}\)$")


def _teams_in_debate_from_result_cell(result_cell: dict | None) -> list[str] | None:
    """Elimination rounds without a public ballot have no per-row debate id to group by, but
    each row's `result` popover lists the debate's full team composition in prose (always in
    OG/OO/CG/CO order), e.g. "Teams in debate:<br />A (OG)<br />B (OO)<br /><strong>C
    (CG)</strong><br />D (CO)". Parsed out, that composition is itself a stable, independently-
    reproducible key every row of the same debate agrees on -- exactly what a shared id is for.
    """
    popover = (result_cell or {}).get("popover") or {}
    for item in popover.get("content", []):
        text = item.get("text", "")
        if "teams in debate" not in text.lower():
            continue
        plain_segments = re.split(r"<br\s*/?>", text)
        names = []
        for seg in plain_segments:
            cleaned = re.sub(r"<[^>]+>", "", seg).strip()
            match = _TEAMS_IN_DEBATE_RE.match(cleaned)
            if match:
                names.append(match.group(1).strip())
        if names:
            return names
    return None


def _synthetic_debate_id(round_seq: int, team_names_in_debate: list[str]) -> int:
    """A deterministic (not just-this-process) stand-in for a real debate external id, used
    only when the page publishes no ballot link to group rows by (see
    `_teams_in_debate_from_result_cell`). CRC32 rather than `hash()`, which is randomized per
    process in Python and would silently break idempotency across scrape cycles."""
    key = f"{round_seq}:{'|'.join(sorted(team_names_in_debate))}"
    return zlib.crc32(key.encode("utf-8"))


def parse_round_results(html: str, round_seq: int) -> list[ScrapedDebate]:
    debates: dict[int, list[ScrapedDebateTeamEntry]] = {}
    adjudicators_by_debate: dict[int, tuple[ScrapedDebateAdjudicator, ...]] = {}
    ballot_url_by_debate: dict[int, str] = {}

    for row in _rows(html):
        team_cell = row.get("team")
        team_ext_id = cell_external_id(team_cell)
        team_name = cell_text(team_cell)
        if team_ext_id is None or not team_name:
            continue

        result_cell = row.get("result") or {}

        ballot_cell = row.get("ballot")
        ballot_link = (
            next(iter(popover_links(ballot_cell)), None) or ballot_cell.get("link")
            if ballot_cell
            else None
        )
        debate_ext_id = external_id_from_link(ballot_link)
        if debate_ext_id is None:
            # No public ballot for this round (common for elimination rounds) -- fall back to
            # a synthetic id derived from the debate's team composition instead of skipping
            # the row outright.
            teams_in_debate = _teams_in_debate_from_result_cell(result_cell)
            if teams_in_debate is None:
                continue
            debate_ext_id = _synthetic_debate_id(round_seq, teams_in_debate)

        side_label = cell_text(row.get("side")) or ""
        position = parse_bp_position(side_label)
        if position is None:
            raise ParseError(f"unrecognized BP position label {side_label!r}", url=None)

        result_label = cell_text(result_cell)
        rank_in_debate = parse_rank_from_label(result_label)
        advanced = _advanced_from_result_label(result_label)

        debates.setdefault(debate_ext_id, []).append(
            ScrapedDebateTeamEntry(
                team_external_id=team_ext_id,
                team_name=team_name,
                position=position,
                rank_in_debate=rank_in_debate,
                result_label=result_label,
                advanced=advanced,
            )
        )
        if ballot_link:
            ballot_url_by_debate[debate_ext_id] = ballot_link

        if debate_ext_id not in adjudicators_by_debate:
            adjudicators_by_debate[debate_ext_id] = tuple(
                _parse_debate_adjudicators(row.get("adjudicators"))
            )

    return [
        ScrapedDebate(
            debate_external_id=debate_id,
            round_seq=round_seq,
            teams=tuple(teams),
            adjudicators=adjudicators_by_debate.get(debate_id, ()),
            ballot_source_url=ballot_url_by_debate.get(debate_id),
        )
        for debate_id, teams in debates.items()
    ]


_JUDGE_LINK_TEXT_RE = re.compile(
    r"View (?P<name>[\w'À-ſ]+)'s\s*\((?P<role>chair|panellist|trainee)", re.IGNORECASE
)


def _parse_debate_adjudicators(cell: dict | None) -> list[ScrapedDebateAdjudicator]:
    if not cell:
        return []
    popover = cell.get("popover") or {}
    out = []
    for item in popover.get("content", []):
        link = item.get("link")
        text = item.get("text", "")
        ext_id = external_id_from_link(link)
        match = _JUDGE_LINK_TEXT_RE.search(text)
        if ext_id is None or not match:
            continue
        role_raw = match.group("role").lower()
        role = {
            "chair": JudgeRole.CHAIR,
            "panellist": JudgeRole.PANELLIST,
            "trainee": JudgeRole.TRAINEE,
        }[role_raw]
        # The link text is "View <FirstName>'s ..." -- only a first name, not reliable as the
        # adjudicator's full name. Full names come from the adjudicator list scrape instead;
        # here we only need the (external_id, role) pairing for this debate.
        out.append(
            ScrapedDebateAdjudicator(external_id=ext_id, name=match.group("name"), role=role)
        )
    return out


# --- Ballot / scoresheet detail page (plain HTML, BeautifulSoup) -----------------------


def parse_ballot(html: str, debate_external_id: int) -> ScrapedBallot:
    soup = BeautifulSoup(html, "lxml")

    small = soup.select_one("#pageTitle small.text-muted")
    round_label, room_name = None, None
    if small and small.get_text(strip=True):
        raw = small.get_text(" ", strip=True)
        parts = raw.split("@", 1)
        round_label = parts[0].strip() or None
        if len(parts) > 1:
            room_name = re.sub(r"\s+", " ", parts[1]).strip() or None

    motion_text = None
    motion_title = soup.find(
        "h4", class_="card-title", string=re.compile(r"^\s*Motion\s*$", re.IGNORECASE)
    )
    if motion_title:
        card_body = motion_title.find_parent(class_="card-body")
        if card_body:
            motion_text = card_body.get_text(" ", strip=True).removeprefix("Motion").strip()

    teams: list[ScrapedBallotTeamBlock] = []
    for block in soup.select("div.col-6.list-group, div.col-md-6.list-group"):
        speaker_scores: list[ScrapedSpeakerScore] = []
        team_name: str | None = None
        position: BPPosition | None = None
        total_score: float | None = None

        for item in block.select("li.list-group-item"):
            # The "Total for TEAM (POSITION)" row is the only one wrapped in <em>. Its
            # container class is a Bootstrap *placement* colour (success/info/warning/danger
            # for 1st/2nd/3rd/4th) rather than a fixed "this is the total row" marker, so we
            # can't key off "list-group-item-success" -- only the top-placed team gets that
            # one, which is why this used to silently drop the other 3 teams in every debate.
            em = item.find("em")
            if em is not None:
                match = re.match(
                    r"Total for (?P<team>.+?)\s*\((?P<position>[^)]+)\)\s*$",
                    em.get_text(strip=True),
                )
                if match:
                    team_name = match.group("team")
                    position = parse_bp_position(match.group("position"))
                badge = item.find("span", class_="badge")
                total_score = _parse_score(badge.get_text(strip=True)) if badge else None
                continue

            role_tag = item.find("strong")
            badge = item.find("span", class_="badge")
            if not isinstance(role_tag, Tag):
                continue
            if badge is not None and not isinstance(badge, Tag):
                badge = None
            try:
                role = SpeakerRole(role_tag.get_text(strip=True))
            except ValueError:
                continue
            speaker_name = _text_between(item, role_tag, badge)
            score = _parse_score(badge.get_text(strip=True)) if badge else None
            speaker_scores.append(
                ScrapedSpeakerScore(team_name="", role=role, speaker_name=speaker_name, score=score)
            )

        if team_name is None or position is None:
            continue

        # Mark iron speeches: the same person delivering both of their team's speeches.
        names = [s.speaker_name for s in speaker_scores]
        is_iron = len(names) == 2 and names[0] == names[1] and names[0] != ""
        speaker_scores = [
            ScrapedSpeakerScore(
                team_name=team_name,
                role=s.role,
                speaker_name=s.speaker_name,
                score=s.score,
                is_iron=is_iron,
            )
            for s in speaker_scores
        ]
        teams.append(
            ScrapedBallotTeamBlock(
                team_name=team_name,
                position=position,
                total_score=total_score,
                speaker_scores=tuple(speaker_scores),
            )
        )

    if not teams:
        raise ParseError("no team scoresheet blocks found on ballot page")

    return ScrapedBallot(
        debate_external_id=debate_external_id,
        room_name=room_name,
        round_label=round_label,
        motion_text=motion_text,
        teams=tuple(teams),
    )


def _text_between(item: Tag, role_tag: Tag, badge: Tag | None) -> str:
    """The speaker's name is the loose text inside a <li> after <strong>role</strong> and
    before the score <span>; there's no dedicated element for it, so we pull it out by
    excluding the tags we already know about and joining what's left."""
    fragments: list[str] = []
    for child in item.children:
        if child is role_tag or child is badge:
            continue
        if isinstance(child, Tag):
            if child.name != "span":
                fragments.append(child.get_text())
        else:
            fragments.append(str(child))
    return " ".join(" ".join(fragments).split())


def _parse_score(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# --- Site-wide navigation: round list & break categories --------------------------------


def parse_round_nav(html: str) -> list[ScrapedRoundRef]:
    soup = BeautifulSoup(html, "lxml")
    menu = soup.find("div", class_="dropdown-menu", attrs={"aria-labelledby": "roundsDrop"})
    if not isinstance(menu, Tag):
        return []
    out = []
    for link in menu.select("a.dropdown-item[href]"):
        seq = _round_seq_from_href(str(link["href"]))
        if seq is None:
            continue
        name = link.get_text(strip=True)
        out.append(
            ScrapedRoundRef(seq=seq, name=name, is_elimination=_looks_like_elimination(name))
        )
    return sorted(out, key=lambda r: r.seq)


def _round_seq_from_href(href: str) -> int | None:
    match = re.search(r"/round/(\d+)/?", href)
    return int(match.group(1)) if match else None


def _looks_like_elimination(name: str) -> bool:
    lowered = name.lower()
    return any(kw in lowered for kw in _ELIMINATION_KEYWORDS)


def parse_break_category_nav(html: str) -> list[ScrapedBreakCategoryRef]:
    soup = BeautifulSoup(html, "lxml")
    menu = soup.find("div", class_="dropdown-menu", attrs={"aria-labelledby": "breakdrop"})
    if not isinstance(menu, Tag):
        return []
    out = []
    for link in menu.select("a.dropdown-item[href]"):
        href = str(link["href"])
        name = link.get_text(strip=True)
        is_adj = href.rstrip("/").endswith("/adjudicators")
        slug_match = re.search(r"/break/([^/]+)/?$", href)
        slug = slug_match.group(1) if slug_match else name.lower().replace(" ", "-")
        out.append(ScrapedBreakCategoryRef(slug=slug, name=name, is_adjudicator_break=is_adj))
    return out


# --- Team break (best-effort: not verified against a live fixture, see README) ----------


def parse_team_break(html: str) -> list[ScrapedTeamBreakEntry]:
    """Parses a team break list page. Written against Tabbycat's documented public template
    for this page, but -- unlike every other parser in this module -- NOT verified against a
    live fixture, because the reference tournament used during development (CMUDE 2025) had
    not reached its team break yet. Column-key lookups make it tolerant of minor differences,
    and any structural mismatch raises ParseError (caught and logged, never silently wrong)
    rather than guessing."""
    rank_key = None
    rows = _rows(html)
    if rows:
        rank_key = next((k for k in rows[0] if k.lower() in ("rk", "rank")), None)
    out = []
    for row in rows:
        team_cell = row.get("team")
        team_name = cell_text(team_cell)
        if not team_name:
            continue
        rank_cell = row.get(rank_key) if rank_key else None
        rank = parse_rank_from_label(cell_text(rank_cell)) if rank_cell else None
        if rank is None and rank_cell:
            sort_val = cell_sort(rank_cell)
            rank = int(sort_val) if isinstance(sort_val, (int, float)) else None
        out.append(
            ScrapedTeamBreakEntry(
                team_external_id=cell_external_id(team_cell), team_name=team_name, rank=rank
            )
        )
    return out
