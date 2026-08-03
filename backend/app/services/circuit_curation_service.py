"""Admin curation for circuit identity matches that `circuit_identity_service` couldn't fully
trust on its own.

`match_or_create_institution`'s fuzzy path (see that module's docstring) is deliberately willing
to auto-link a near-miss spelling, flagging the alias `confirmed=False` rather than blocking on
it -- see that flag's own docstring on `CircuitInstitutionAlias` for why it's still usable in the
meantime. This service is the other half: surfacing exactly those unconfirmed attributions to an
admin, and letting them correct or confirm one -- reassign the SPECIFIC tournament-scoped
`Institution` row to a different (existing or brand-new) `CircuitInstitution`, never a blanket
merge of every row already linked to the old one. A human catching a case the string-similarity
heuristic structurally can't (e.g. an abbreviation the same institution used one year, with too
little character overlap to ever score as fuzzy) is exactly the gap this closes.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.circuit import CircuitInstitution, CircuitInstitutionAlias
from app.models.participants import Institution, Team
from app.services.circuit_identity_service import normalize_name, slugify, unique_slug


@dataclass(frozen=True)
class ReviewItem:
    institution: Institution
    circuit_institution: CircuitInstitution


async def _resolve_or_create_target(
    session: AsyncSession,
    *,
    circuit_institution_id: int | None,
    new_institution_name: str | None,
    new_institution_region: str | None,
) -> CircuitInstitution:
    """Shared by both admin actions below: point at an existing circuit identity, or create a
    brand-new one from a name the admin typed in."""
    if circuit_institution_id is not None:
        target = await session.get(CircuitInstitution, circuit_institution_id)
        if target is None:
            raise ValueError(f"circuit institution {circuit_institution_id} not found")
        return target
    if new_institution_name is not None:
        slug = await unique_slug(session, CircuitInstitution, slugify(new_institution_name))
        target = CircuitInstitution(
            name=new_institution_name, slug=slug, region=new_institution_region
        )
        session.add(target)
        await session.flush()
        return target
    raise ValueError("must provide either circuit_institution_id or new_institution_name")


async def list_review_queue(session: AsyncSession) -> list[ReviewItem]:
    """Every tournament-scoped Institution row whose current circuit-identity link came from an
    unconfirmed (fuzzy) match. Filtered in Python against the small, already-fetched candidate
    set rather than in SQL, since matching requires `normalize_name` (accent/case folding) --
    same "the tables are small, a round trip doesn't matter" reasoning as repositories/upsert.py.
    """
    unconfirmed = (
        await session.execute(
            select(CircuitInstitutionAlias).where(CircuitInstitutionAlias.confirmed.is_(False))
        )
    ).scalars().all()
    if not unconfirmed:
        return []

    unconfirmed_aliases_by_circuit_id: dict[int, set[str]] = defaultdict(set)
    for alias in unconfirmed:
        unconfirmed_aliases_by_circuit_id[alias.circuit_institution_id].add(alias.alias)

    candidates = (
        await session.execute(
            select(Institution).where(
                Institution.circuit_institution_id.in_(unconfirmed_aliases_by_circuit_id)
            )
        )
    ).scalars().all()

    items = []
    for institution in candidates:
        # Never actually None here: the query above filtered to rows whose
        # circuit_institution_id is IN unconfirmed_aliases_by_circuit_id's keys.
        assert institution.circuit_institution_id is not None
        flagged_aliases = unconfirmed_aliases_by_circuit_id[institution.circuit_institution_id]
        if (
            normalize_name(institution.name) in flagged_aliases
            or normalize_name(institution.code) in flagged_aliases
        ):
            circuit_institution = await session.get(
                CircuitInstitution, institution.circuit_institution_id
            )
            assert circuit_institution is not None
            items.append(ReviewItem(institution=institution, circuit_institution=circuit_institution))
    return items


async def resolve_review_item(
    session: AsyncSession,
    institution: Institution,
    *,
    circuit_institution_id: int | None,
    new_institution_name: str | None,
    new_institution_region: str | None,
) -> CircuitInstitution:
    """Points `institution` at `circuit_institution_id` (an existing identity -- pass the SAME
    id it already has to mean "the auto-match was right, just confirm it") or, if
    `new_institution_name` is given instead, creates a brand-new CircuitInstitution first. Either
    way, the alias for this institution's own name/code is upserted as `confirmed=True` on the
    target -- `alias` is globally unique, so an existing row for this name/code (pointing at the
    WRONG identity) gets its `circuit_institution_id` corrected in place rather than duplicated.
    """
    target = await _resolve_or_create_target(
        session,
        circuit_institution_id=circuit_institution_id,
        new_institution_name=new_institution_name,
        new_institution_region=new_institution_region,
    )

    institution.circuit_institution_id = target.id
    if target.region is None and institution.region is not None:
        target.region = institution.region

    for key in {normalize_name(institution.name), normalize_name(institution.code)}:
        alias = (
            await session.execute(
                select(CircuitInstitutionAlias).where(CircuitInstitutionAlias.alias == key)
            )
        ).scalar_one_or_none()
        if alias is None:
            session.add(
                CircuitInstitutionAlias(circuit_institution_id=target.id, alias=key, confirmed=True)
            )
        else:
            alias.circuit_institution_id = target.id
            alias.confirmed = True

    await session.flush()
    return target


async def list_unassigned_teams(session: AsyncSession) -> list[Team]:
    """Teams the automatic prefix heuristic (_match_institution_by_name_prefix in
    services.ingestion) couldn't link to any institution scraped for their own tournament --
    the OTHER gap this service closes, distinct from the fuzzy-match review queue above (that
    one is about an Institution row pointing at the wrong circuit identity; this one is about a
    Team never getting ANY institution_id at all)."""
    return list(
        (
            await session.execute(select(Team).where(Team.institution_id.is_(None)))
        )
        .scalars()
        .all()
    )


async def assign_team_institution(
    session: AsyncSession,
    team: Team,
    *,
    circuit_institution_id: int | None,
    new_institution_name: str | None,
    new_institution_region: str | None,
) -> Institution:
    """Admin override for a team `list_unassigned_teams` surfaced: point it at the tournament's
    existing Institution row for the chosen circuit identity, creating one if this tournament
    never scraped an institution entry under that identity (common for backfilled tournaments,
    or an institution whose entry the source site simply never listed). Never touches the alias
    table -- a TEAM name ("PUCP FM") isn't a usable institution name/code variant, unlike
    `resolve_review_item`'s case where the row being fixed IS an Institution."""
    target = await _resolve_or_create_target(
        session,
        circuit_institution_id=circuit_institution_id,
        new_institution_name=new_institution_name,
        new_institution_region=new_institution_region,
    )

    institution = (
        await session.execute(
            select(Institution).where(
                Institution.tournament_id == team.tournament_id,
                Institution.circuit_institution_id == target.id,
            )
        )
    ).scalars().first()

    if institution is None:
        institution = Institution(
            tournament_id=team.tournament_id,
            code=slugify(target.name).upper()[:50],
            name=target.name,
            region=target.region,
            circuit_institution_id=target.id,
        )
        session.add(institution)
        await session.flush()

    team.institution_id = institution.id
    await session.flush()
    return institution
