"""Generic idempotent upsert against a natural key, with field-level change detection.

This is the single mechanism every ingestion step in `services/ingestion.py` uses to write
scraped data: look the row up by its natural key (never the surrogate `id`, which the scraper
doesn't know), create it if missing, or update only the fields that actually differ. The
returned diff is exactly what `ChangeEvent` rows are built from -- a no-op re-scrape (nothing on
the page changed) touches no `updated_at` timestamps and produces no ChangeEvent, which is what
keeps "detectar cambios recientes" meaningful instead of firing on every single poll.

Deliberately implemented as SELECT-then-write rather than a dialect-specific
`INSERT ... ON CONFLICT` statement: this application's tables are small (hundreds of rows, not
millions), so the extra round-trip is irrelevant, and doing the diff in Python lets this same
code run unmodified against SQLite in tests and Postgres in production.
"""

from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


@dataclass
class UpsertResult:
    instance: Any
    created: bool
    changed_fields: dict[str, dict[str, Any]]

    @property
    def changed(self) -> bool:
        return self.created or bool(self.changed_fields)


async def upsert_by_natural_key(
    session: AsyncSession,
    model: type[ModelT],
    *,
    lookup: dict[str, Any],
    values: dict[str, Any],
) -> UpsertResult:
    """Find `model` by `lookup` (its natural key columns) and ensure `values` are set on it.

    `values` should NOT include the lookup columns themselves (they're already fixed by the
    lookup) -- pass everything else that the scraper knows about this entity.
    """
    stmt = select(model).filter_by(**lookup)
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing is None:
        instance = model(**lookup, **values)
        session.add(instance)
        await session.flush()
        created_fields = {k: {"old": None, "new": v} for k, v in values.items()}
        return UpsertResult(instance=instance, created=True, changed_fields=created_fields)

    changed_fields: dict[str, dict[str, Any]] = {}
    for key, new_value in values.items():
        old_value = getattr(existing, key)
        if old_value != new_value:
            changed_fields[key] = {"old": old_value, "new": new_value}
            setattr(existing, key, new_value)

    if changed_fields:
        await session.flush()

    return UpsertResult(instance=existing, created=False, changed_fields=changed_fields)
