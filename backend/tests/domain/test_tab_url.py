import pytest

from app.domain.tab_url import parse_tab_url


@pytest.mark.parametrize(
    "raw_url,expected_base,expected_slug",
    [
        (
            "https://cmude2025.calicotab.com/open/participants/list/",
            "https://cmude2025.calicotab.com",
            "open",
        ),
        ("https://cmude2025.calicotab.com/open/", "https://cmude2025.calicotab.com", "open"),
        ("https://cmude2025.calicotab.com/open", "https://cmude2025.calicotab.com", "open"),
        (
            "https://CMUDE2025.calicotab.com/Open/participants/list/",
            "https://cmude2025.calicotab.com",
            "Open",
        ),
        (
            "cmude2025.calicotab.com/open/participants/list/",
            "https://cmude2025.calicotab.com",
            "open",
        ),
        (
            "  https://cmude2025.calicotab.com/masters/results/round/3/  ",
            "https://cmude2025.calicotab.com",
            "masters",
        ),
    ],
)
def test_parse_tab_url_extracts_base_and_slug(raw_url, expected_base, expected_slug) -> None:
    base_url, slug = parse_tab_url(raw_url)
    assert base_url == expected_base
    assert slug == expected_slug


@pytest.mark.parametrize(
    "raw_url",
    [
        "",
        "   ",
        "not a url at all",
        "ftp://cmude2025.calicotab.com/open/",
        "https://cmude2025.calicotab.com/",
        "https://cmude2025.calicotab.com",
    ],
)
def test_parse_tab_url_rejects_unrecognizable_input(raw_url) -> None:
    with pytest.raises(ValueError):
        parse_tab_url(raw_url)
