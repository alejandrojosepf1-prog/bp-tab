import pytest

from app.scraper.exceptions import ParseError
from app.scraper.vuedata import (
    external_id_from_link,
    extract_tables_data,
    row_to_dict,
)


def test_extract_tables_data_on_real_fixture(fixture_html) -> None:
    html = fixture_html("team_tab.html")
    tables = extract_tables_data(html)
    assert len(tables) == 1
    assert {col["key"] for col in tables[0]["head"]} >= {"Rk", "team", "Pts", "Spk"}
    assert len(tables[0]["data"]) == 146


def test_extract_tables_data_raises_parse_error_on_missing_marker() -> None:
    with pytest.raises(ParseError):
        extract_tables_data("<html><body>nothing here</body></html>")


def test_row_to_dict_maps_by_key_not_position() -> None:
    head = [{"key": "a"}, {"key": "b"}]
    row = [{"text": "1"}, {"text": "2"}]
    assert row_to_dict(head, row) == {"a": {"text": "1"}, "b": {"text": "2"}}


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("/open/participants/team/259867/", 259867),
        ("/open/participants/adjudicator/908500/", 908500),
        ("/open/results/debate/443236/scoresheets/", 443236),
        (None, None),
        ("/open/participants/list/", None),
    ],
)
def test_external_id_from_link(link, expected) -> None:
    assert external_id_from_link(link) == expected
