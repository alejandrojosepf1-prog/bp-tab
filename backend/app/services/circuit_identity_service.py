"""Cross-tournament identity resolution for institutions and people.

Institution/Speaker/Adjudicator (app.models.participants) all stay tournament-scoped -- this
service never touches that. It only resolves each one's name to an optional circuit-wide
identity (app.models.circuit.CircuitInstitution / CircuitPerson), called from
services.ingestion as each tournament (new or backfilled) is ingested.

Two very different reliability profiles drive the two matchers below:
  - Institution names are short, fairly standardized codes (see Institution's own docstring)
    with a small, stable vocabulary across the circuit -- exact matches dominate, and a fuzzy
    near-miss ("Pontificia Universidad Catolica" vs "...Católica") is still safe to auto-link
    while flagging for a quick admin confirmation.
  - Person names collide constantly across a Spanish-speaking circuit with no shared id (many
    "Juan Pérez"), so this matcher is deliberately conservative: only an EXACT normalized match
    auto-links; anything else creates a brand-new CircuitPerson rather than guessing a merge.
    Merging two different people under one identity silently corrupts both their histories;
    leaving two entries for the same person unmerged is a visible, cheap admin fix later.
"""

import asyncio
import re
import unicodedata
from difflib import SequenceMatcher
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.models.circuit import (
    CircuitInstitution,
    CircuitInstitutionAlias,
    CircuitPerson,
    CircuitPersonAlias,
)

ModelT = TypeVar("ModelT", bound=Base)

# CircuitInstitution/CircuitPerson are the only GLOBAL (non-tournament-scoped) tables this
# service writes to, so they're the only place two DIFFERENT tournaments' scrapes running at
# the same time (a manual "Forzar scraping" overlapping autoscrape's cycle, or two admins
# acting at once -- autoscrape itself scrapes tournaments strictly one at a time, see
# app.tasks.autoscrape) can genuinely race to create the SAME brand-new identity. How many
# times to retry the create-new path on that conflict before giving up and letting the error
# propagate -- a single scrape failing outright is already handled gracefully by the caller
# (autoscrape logs it and retries next cycle; a manual scrape just shows an error to retry).
_MAX_CREATE_ATTEMPTS = 3

# Below this similarity ratio, a name is treated as a genuinely different institution rather
# than a spelling variant of a known one. 0.87 (the original guess here) turned out to be far
# too permissive: a dry run against real CMUDE 2025 data (62 institutions) confirmed
# SequenceMatcher's character-level ratio is dominated by shared PREFIX length, so Latin
# American university names -- which conventionally share a long formal prefix and differ only
# in a short, meaningful trailing qualifier -- score deceptively high:
#   "Pontificia Universidad Catolica del Peru" vs "...del Ecuador"                  -> 0.916
#   "...Monterrey Campus Toluca" vs "...Monterrey Campus Estado de Mexico"          -> 0.897
#   "Universidad de Piura Sede Piura" vs "Universidad de Piura Sede Lima"           -> 0.918
# All three are genuinely different institutions that got silently merged under the old
# threshold. A real typo of the same name variant, for comparison, scores 0.987. 0.95 sits
# cleanly between those two clusters -- see test_circuit_identity_service.py's regression tests
# for exactly these three real pairs.
INSTITUTION_FUZZY_THRESHOLD = 0.95


def normalize_name(name: str) -> str:
    """Case/accent/whitespace-insensitive key for matching -- 'Pontificia Universidad Católica'
    and 'PONTIFICIA UNIVERSIDAD CATOLICA' normalize to the same string."""
    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_accents.split())


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "sin-nombre"


async def unique_slug(session: AsyncSession, model: type[ModelT], base: str) -> str:
    """`base` with a numeric suffix appended only if it collides -- person names in particular
    collide often by design (see module docstring), so this is expected to trigger regularly,
    not an edge case."""
    slug = base
    suffix = 2
    while (
        await session.execute(select(model).filter_by(slug=slug))
    ).scalar_one_or_none() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


async def match_or_create_institution(
    session: AsyncSession, name: str, code: str, region: str | None = None
) -> tuple[CircuitInstitution, bool]:
    """Resolve one tournament's Institution `name`/`code` to a circuit-wide identity.

    Returns `(institution, needs_review)` -- `needs_review=True` means the match was fuzzy and
    should surface in an admin curation queue rather than being trusted blind. An exact alias
    hit (on either the full name or the short code) is the only case considered fully confirmed.

    `region` (see Institution.region's docstring -- in practice the country) backfills
    CircuitInstitution.region the first time it's known, for the admin curation UI's
    group-by-country picker (app.services.circuit_curation_service). Never overwrites an
    already-set region -- a disagreement between years is a rare edge case, not worth the
    churn of picking a "latest wins" rule for.
    """
    name_key = normalize_name(name)
    code_key = normalize_name(code)

    exact = (
        await session.execute(
            select(CircuitInstitutionAlias).where(
                CircuitInstitutionAlias.alias.in_({name_key, code_key})
            )
        )
    ).scalars().first()
    if exact is not None:
        institution = await session.get(CircuitInstitution, exact.circuit_institution_id)
        assert institution is not None
        if institution.region is None and region is not None:
            institution.region = region
        return institution, False

    all_aliases = (await session.execute(select(CircuitInstitutionAlias))).scalars().all()
    best_alias, best_ratio = None, 0.0
    for alias in all_aliases:
        ratio = SequenceMatcher(None, name_key, alias.alias).ratio()
        if ratio > best_ratio:
            best_ratio, best_alias = ratio, alias

    if best_alias is not None and best_ratio >= INSTITUTION_FUZZY_THRESHOLD:
        institution = await session.get(CircuitInstitution, best_alias.circuit_institution_id)
        assert institution is not None
        if institution.region is None and region is not None:
            institution.region = region
        session.add(
            CircuitInstitutionAlias(
                circuit_institution_id=institution.id, alias=name_key, confirmed=False
            )
        )
        await session.flush()
        return institution, True

    for attempt in range(_MAX_CREATE_ATTEMPTS):
        try:
            async with session.begin_nested():
                slug = await unique_slug(session, CircuitInstitution, slugify(name))
                institution = CircuitInstitution(name=name, slug=slug, region=region)
                session.add(institution)
                await session.flush()
                session.add(
                    CircuitInstitutionAlias(
                        circuit_institution_id=institution.id, alias=name_key, confirmed=True
                    )
                )
                if code_key != name_key:
                    session.add(
                        CircuitInstitutionAlias(
                            circuit_institution_id=institution.id, alias=code_key, confirmed=True
                        )
                    )
                await session.flush()
            return institution, False
        except IntegrityError:
            if attempt == _MAX_CREATE_ATTEMPTS - 1:
                raise
            # The savepoint rollback (automatic on exception exit) undoes only this attempt's
            # half-written institution/aliases, not anything else this ingestion run already
            # staged. The concurrent writer may not have committed yet either -- a short wait
            # before re-checking is the whole fix; it's a rare coincidence, not a hot path.
            await asyncio.sleep(0.1 * (attempt + 1))
            exact = (
                await session.execute(
                    select(CircuitInstitutionAlias).where(
                        CircuitInstitutionAlias.alias.in_({name_key, code_key})
                    )
                )
            ).scalars().first()
            if exact is not None:
                institution = await session.get(CircuitInstitution, exact.circuit_institution_id)
                assert institution is not None
                return institution, False
    raise AssertionError("unreachable")  # pragma: no cover


async def match_or_create_person(session: AsyncSession, name: str) -> CircuitPerson:
    """Resolve one tournament's Speaker/Adjudicator `name` to a circuit-wide identity. Exact
    normalized match only -- see module docstring for why this never fuzzy-matches."""
    key = normalize_name(name)
    existing_alias = (
        await session.execute(select(CircuitPersonAlias).where(CircuitPersonAlias.alias == key))
    ).scalar_one_or_none()
    if existing_alias is not None:
        person = await session.get(CircuitPerson, existing_alias.circuit_person_id)
        assert person is not None
        return person

    slug = await unique_slug(session, CircuitPerson, slugify(name))
    person = CircuitPerson(display_name=name, slug=slug)
    session.add(person)
    await session.flush()
    session.add(CircuitPersonAlias(circuit_person_id=person.id, alias=key))
    await session.flush()
    return person
