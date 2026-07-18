from app.models.enums import BPPosition, JudgeRole, SpeakerRole
from app.scraper import parsers


def test_parse_institutions(fixture_html) -> None:
    institutions = parsers.parse_institutions(fixture_html("institutions_list.html"))
    assert len(institutions) == 62
    pucp = next(i for i in institutions if i.code == "PUCP")
    assert pucp.name == "Pontificia Universidad Católica del Perú"
    assert pucp.region == "Perú"


def test_parse_adjudicators_from_participants_list(fixture_html) -> None:
    adjudicators = parsers.parse_adjudicators(fixture_html("participants_list.html"))
    assert len(adjudicators) == 140
    diego = next(a for a in adjudicators if a.external_id == 908548)
    assert diego.name == "Diego Nuñez del Prado Velarde"
    assert diego.is_independent is True
    assert diego.broke is False
    assert sum(1 for a in adjudicators if a.is_independent) == 14


def test_parse_adjudicators_break_flag(fixture_html) -> None:
    broken = parsers.parse_adjudicators(fixture_html("break_adjudicators.html"), broke=True)
    assert len(broken) == 48
    assert all(a.broke for a in broken)


def test_parse_team_tab(fixture_html) -> None:
    teams = parsers.parse_team_tab(fixture_html("team_tab.html"))
    assert len(teams) == 146
    pucp_fm = next(t for t in teams if t.external_id == 259867)
    assert pucp_fm.name == "PUCP FM"
    assert pucp_fm.emoji == "\U0001f4f1"
    assert pucp_fm.points == 25
    assert pucp_fm.speaker_total == 1477.0
    assert set(pucp_fm.speaker_names) == {"Fernanda Crousillat Rayter", "Mauricio Jarufe Caballero"}

    categorized = [t for t in teams if t.category_names]
    assert categorized, "expected at least one team with a break category tag"


def test_parse_speakers_from_participants_list(fixture_html) -> None:
    html = fixture_html("participants_list.html")
    idx = parsers.find_speaker_table_index(html)
    speakers = parsers.parse_speakers(html, table_index=idx)
    assert len(speakers) == 292
    with_category = [s for s in speakers if s.category_names]
    assert with_category
    assert with_category[0].category_names == ("ELE",)


def test_parse_speaker_tab(fixture_html) -> None:
    speakers = parsers.parse_speakers(fixture_html("speaker_tab.html"))
    assert len(speakers) == 292
    assert speakers[0].name == "Fernanda Crousillat Rayter"
    assert speakers[0].team_external_id == 259867


def test_parse_round_results_groups_rows_into_debates(fixture_html) -> None:
    debates = parsers.parse_round_results(fixture_html("round_results_9.html"), round_seq=9)
    # 140 team-rows / 4 teams per BP debate == 35 debates.
    assert len(debates) == 35
    debate = next(d for d in debates if d.debate_external_id == 443236)
    assert debate.round_seq == 9
    assert debate.ballot_source_url == "/open/results/debate/443236/scoresheets/"
    positions = {t.position for t in debate.teams}
    assert positions == {
        BPPosition.OPENING_GOVERNMENT,
        BPPosition.OPENING_OPPOSITION,
        BPPosition.CLOSING_GOVERNMENT,
        BPPosition.CLOSING_OPPOSITION,
    }
    ranks = sorted(t.rank_in_debate for t in debate.teams)
    assert ranks == [1, 2, 3, 4]
    assert {a.role for a in debate.adjudicators} == {
        JudgeRole.CHAIR,
        JudgeRole.PANELLIST,
        JudgeRole.TRAINEE,
    }


def test_parse_round_results_elimination_round_without_public_ballot(fixture_html) -> None:
    """The Grand Final (round 13) publishes no ballot link and uses "Advancing"/"Eliminated"
    labels instead of numeric ranks -- the debate id has to be synthesized from the "Teams in
    debate" popover prose instead of a ballot URL (see `_synthetic_debate_id` in parsers.py)."""
    debates = parsers.parse_round_results(fixture_html("round_results_13_final.html"), round_seq=13)
    assert len(debates) == 1
    debate = debates[0]
    assert debate.round_seq == 13
    assert debate.ballot_source_url is None
    assert len(debate.teams) == 4
    assert all(t.rank_in_debate is None for t in debate.teams)

    by_name = {t.team_name: t for t in debate.teams}
    assert set(by_name) == {"UPV GG", "Rosario LT", "PUCP FM", "GAD - UAB GG"}
    assert by_name["PUCP FM"].advanced is True
    assert by_name["PUCP FM"].position == BPPosition.CLOSING_GOVERNMENT
    for name in ("UPV GG", "Rosario LT", "GAD - UAB GG"):
        assert by_name[name].advanced is False

    # The grouping key matches what an independent caller would derive from the same team names.
    assert debate.debate_external_id == parsers._synthetic_debate_id(13, sorted(by_name))


def test_parse_ballot(fixture_html) -> None:
    ballot = parsers.parse_ballot(fixture_html("ballot_443236.html"), debate_external_id=443236)
    assert ballot.debate_external_id == 443236
    assert ballot.round_label == "Ronda 9"
    assert "A-233" in ballot.room_name
    assert ballot.motion_text.startswith("EC, siendo el movimiento LGBTIAQ+")
    assert len(ballot.teams) == 4

    og_block = next(t for t in ballot.teams if t.position == BPPosition.OPENING_GOVERNMENT)
    assert og_block.team_name == "UAQ SG"
    assert og_block.total_score == 143.0
    assert len(og_block.speaker_scores) == 2
    pm = next(s for s in og_block.speaker_scores if s.role == SpeakerRole.PM)
    assert pm.speaker_name == "Lucia Mildre Sánchez Razo"
    assert pm.score == 71.0
    assert pm.is_iron is False


def test_parse_round_nav_classifies_elimination_stage(fixture_html) -> None:
    rounds = parsers.parse_round_nav(fixture_html("ballot_443236.html"))
    assert len(rounds) == 13
    by_seq = {r.seq: r for r in rounds}
    assert by_seq[9].name == "Ronda 9"
    assert by_seq[9].is_elimination is False
    assert by_seq[10].is_elimination is True  # Octavos de Final
    assert by_seq[13].is_elimination is True  # Gran Final


def test_parse_break_category_nav(fixture_html) -> None:
    categories = parsers.parse_break_category_nav(fixture_html("ballot_443236.html"))
    assert len(categories) == 1
    assert categories[0].is_adjudicator_break is True
    assert categories[0].slug == "adjudicators"
