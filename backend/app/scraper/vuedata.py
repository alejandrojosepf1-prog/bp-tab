"""Extraction of Tabbycat's embedded ``window.vueData`` table blob.

Every CalicoTab "tab" page (team tab, speaker tab, round results, participants list,
institutions list, break lists) is server-rendered HTML that embeds a Vue component's
input data directly in a ``<script>`` tag:

    window.vueData = {
      tablesData: [{"head": [...], "data": [[...], ...]}, ...]
    }

Vue only uses this to *paint* the table client-side -- the full structured data is already
present in the initial HTML response, so we never need a JS-executing browser to read it.

The outer object uses a bare (unquoted) JS key -- ``{tablesData: [...]}`` -- which is valid
JavaScript but not valid JSON, so the whole blob can't be handed to ``json.loads`` directly.
The array *value* is always emitted as strict JSON, so we locate ``tablesData:`` and
bracket-match from the following ``[`` to its balanced ``]``, then parse just that array.
We deliberately never ``eval()``/execute the script contents -- this is third-party content.
"""

import re
from typing import Any

from app.scraper.exceptions import ParseError

_EXTERNAL_ID_RE = re.compile(r"/(\d+)/")


def extract_tables_data(html: str) -> list[dict[str, Any]]:
    """Return the list of ``{"head": [...], "data": [...]}`` tables embedded in the page."""
    marker = "tablesData:"
    try:
        key_idx = html.index(marker)
        start = html.index("[", key_idx + len(marker))
    except ValueError as exc:
        raise ParseError("no window.vueData/tablesData block found in page") from exc

    end = _find_matching_bracket(html, start)
    if end is None:
        raise ParseError("tablesData array is not properly terminated")

    import json

    try:
        return json.loads(html[start:end])
    except json.JSONDecodeError as exc:
        raise ParseError(f"tablesData block is not valid JSON: {exc}") from exc


def _find_matching_bracket(html: str, open_index: int) -> int | None:
    """Return the index just past the ``]`` that matches the ``[`` at ``open_index``,
    correctly skipping brackets that appear inside JSON string literals."""
    depth = 0
    in_string = False
    escape = False
    for i in range(open_index, len(html)):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return i + 1
    return None


def row_to_dict(head: list[dict[str, Any]], row: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Zip a table's ``head`` column spec with one ``data`` row into ``{column_key: cell}``.

    Looking cells up by column key (rather than a positional index) is what makes the parsers
    tolerant of Tabbycat re-ordering or adding columns -- only a renamed/removed key breaks us.
    """
    result: dict[str, dict[str, Any]] = {}
    for col, cell in zip(head, row, strict=False):
        key = col.get("key")
        if key is not None:
            result[key] = cell
    return result


def cell_text(cell: dict[str, Any] | None) -> str | None:
    if not cell:
        return None
    text = cell.get("text")
    return text.strip() if isinstance(text, str) else None


def cell_sort(cell: dict[str, Any] | None) -> Any:
    if not cell:
        return None
    return cell.get("sort")


def cell_emoji(cell: dict[str, Any] | None) -> str | None:
    if not cell:
        return None
    return cell.get("emoji")


def popover_links(cell: dict[str, Any] | None) -> list[str]:
    """All hrefs found in a cell's popover content (e.g. 'View X's Record' links)."""
    if not cell:
        return []
    popover = cell.get("popover") or {}
    return [item["link"] for item in popover.get("content", []) if item.get("link")]


def external_id_from_link(link: str | None) -> int | None:
    """Pull the id out of a CalicoTab detail URL. The id isn't always the last path segment --
    e.g. a ballot link is '/open/results/debate/443236/scoresheets/' -- so we take the LAST
    slash-delimited numeric segment in the path rather than anchoring to the end of the string."""
    if not link:
        return None
    matches = _EXTERNAL_ID_RE.findall(link)
    return int(matches[-1]) if matches else None


def cell_external_id(cell: dict[str, Any] | None) -> int | None:
    """Convenience: the external id referenced by a cell's own popover record link, if any."""
    for link in popover_links(cell):
        ext_id = external_id_from_link(link)
        if ext_id is not None:
            return ext_id
    return None
