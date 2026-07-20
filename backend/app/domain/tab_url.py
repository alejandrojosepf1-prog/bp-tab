"""Parses a single CalicoTab "tab" URL into the (source_base_url, source_slug) pair the rest of
the system uses as a tournament's external identity.

Pure function, no DB/FastAPI dependency -- lets the admin paste one URL (e.g. the exact link they
copied from their browser, `https://cmude2025.calicotab.com/open/participants/list/`) instead of
manually splitting it into two form fields, which was error-prone and the #1 friction point in
registering a new tournament.
"""

import re
from urllib.parse import urlsplit, urlunsplit

_SLUG_RE = re.compile(r"^/([^/]+)/?")


def parse_tab_url(raw_url: str) -> tuple[str, str]:
    """Returns (source_base_url, source_slug), both normalized for stable dedup against
    Tournament's `uq_tournaments_source` unique constraint: scheme/host lowercased, no
    trailing slash on base_url, slug stripped of surrounding slashes.

    Raises ValueError with a human-readable message on anything that isn't a recognizable tab
    URL -- the caller (the tournaments router) turns that into a 422 for the admin to fix.
    """
    candidate = raw_url.strip()
    if not candidate:
        raise ValueError("La URL no puede estar vacía.")
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"'{raw_url}' no parece una URL válida.")

    match = _SLUG_RE.match(parts.path or "")
    if not match:
        raise ValueError(
            f"No se encontró el slug del torneo en '{raw_url}'. Se espera algo como "
            "https://cmude2025.calicotab.com/open/participants/list/ (el slug es 'open')."
        )

    source_slug = match.group(1)
    source_base_url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), "", "", ""))
    return source_base_url, source_slug
