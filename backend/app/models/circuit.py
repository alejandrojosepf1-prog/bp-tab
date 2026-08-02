"""Circuit-wide identity, decoupled from any single tournament.

`Institution`/`Speaker`/`Adjudicator` (app.models.participants) all stay `TournamentScopedMixin`
-- CalicoTab has no persistent id for any of them across tournaments, and changing that scoping
would touch every natural-key upsert already written against it (see repositories/upsert.py).
Instead, `CircuitInstitution`/`CircuitPerson` here are purely additive: a per-tournament row
OPTIONALLY links to one of these via a nullable FK (`circuit_institution_id` /
`circuit_person_id`), populated by `app.services.circuit_identity_service` as tournaments are
ingested (new and backfilled alike). Nothing about existing per-tournament queries, markets, or
settlement changes -- this only exists to answer cross-tournament questions ("every tournament
PUCP has attended") for the public circuit archive.

Each identity keeps a table of every raw name variant it's ever been matched from (`aliases`),
because CalicoTab exposes no canonical spelling and the same institution/person shows up
differently across tournaments and years ("PUCP" vs "Pontificia Universidad Católica del Perú").
See `circuit_identity_service`'s module docstring for why institution matching tolerates fuzzy
matches (flagged via `confirmed=False` for an admin curation queue) while person matching
deliberately does not.
"""

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class CircuitInstitution(Base, TimestampMixin):
    """One institution's identity across every backfilled tournament -- the entity a public
    `/instituciones/:slug` page is about, distinct from the per-tournament `Institution` rows
    that actually drive scraping/ingestion/markets."""

    __tablename__ = "circuit_institutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), nullable=False, unique=True, index=True)
    # Backfilled from Institution.region the first time it's known (see
    # circuit_identity_service.match_or_create_institution) -- in practice the country, per that
    # column's own docstring. Powers the admin curation UI's group-by-country picker
    # (app.services.circuit_curation_service). Never overwritten once set.
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)

    aliases = relationship(
        "CircuitInstitutionAlias", back_populates="institution", cascade="all, delete-orphan"
    )


class CircuitInstitutionAlias(Base):
    """One raw name/code variant that has been matched to a `CircuitInstitution`.

    `confirmed=False` means the match came from fuzzy similarity, not an exact hit, and should
    surface in an admin curation queue -- but it's still used for matching in the meantime (a
    later ingestion seeing this exact alias again resolves here too), since leaving it
    unusable until reviewed would just recreate the same fuzzy-match decision on every re-scrape.
    Review corrects a wrong attribution; it doesn't gate whether the alias works at all.
    """

    __tablename__ = "circuit_institution_aliases"
    __table_args__ = (UniqueConstraint("alias", name="uq_circuit_institution_aliases_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    circuit_institution_id: Mapped[int] = mapped_column(
        ForeignKey("circuit_institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Normalized (circuit_identity_service.normalize_name) form of a name/code seen for this
    # institution -- never the raw scraped string, so looking up a freshly-normalized incoming
    # name is a direct unique-index hit instead of a scan.
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    institution = relationship("CircuitInstitution", back_populates="aliases")


class CircuitPerson(Base, TimestampMixin):
    """One person's identity across every backfilled tournament, regardless of whether they
    appear as a `Speaker`, an `Adjudicator`, or (common -- alumni return to judge) both over the
    years. See `circuit_identity_service`'s module docstring for why matching here is
    deliberately more conservative than `CircuitInstitution`'s: names collide constantly across
    a circuit with no shared id, so only an exact match auto-links -- there is no fuzzy/
    `confirmed` path here, unlike institutions."""

    __tablename__ = "circuit_people"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)

    aliases = relationship(
        "CircuitPersonAlias", back_populates="person", cascade="all, delete-orphan"
    )


class CircuitPersonAlias(Base):
    __tablename__ = "circuit_person_aliases"
    __table_args__ = (UniqueConstraint("alias", name="uq_circuit_person_aliases_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    circuit_person_id: Mapped[int] = mapped_column(
        ForeignKey("circuit_people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(300), nullable=False)

    person = relationship("CircuitPerson", back_populates="aliases")
