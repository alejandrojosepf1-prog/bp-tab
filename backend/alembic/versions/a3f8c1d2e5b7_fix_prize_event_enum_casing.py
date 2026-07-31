"""fix prize event enum casing

`prizeeventtype`/`prizeeventstatus` were created with lowercase Postgres enum values
('manual_award', 'raffle', ...) matching PrizeEventType/PrizeEventStatus's Python `.value`
strings. But SQLAlchemy's default `Enum` type binds a Python enum member by its NAME, not its
`.value`, unless told otherwise (`values_callable=...`) -- exactly how `bettype` was migrated
(uppercase member names: CHAMPION, ROUND_WINNER, ...), and how every other enum column in this
app actually round-trips correctly. Every INSERT into `prize_events` sent 'RAFFLE'/'OPEN' etc.
against a type that only accepted the lowercase spelling, so every prize-event creation failed
with asyncpg's InvalidTextRepresentationError -- 100% reproducible, not a fluke: confirmed via
Render logs that this failed for the FIRST-EVER attempt to create a prize event in production,
the day after the feature shipped.

Because the write always failed, no `prize_events` row could ever have been persisted with a
real type/status value -- confirmed empty via the public API before writing this -- so this is
a pure schema fix, no data to migrate.

Revision ID: a3f8c1d2e5b7
Revises: c9f2a6e1b8d4
Create Date: 2026-07-31 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a3f8c1d2e5b7'
down_revision: Union[str, None] = 'c9f2a6e1b8d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE prizeeventtype RENAME TO prizeeventtype_old")
    op.execute("CREATE TYPE prizeeventtype AS ENUM ('MANUAL_AWARD', 'RAFFLE', 'ACTIVITY_BONUS')")
    op.execute(
        "ALTER TABLE prize_events ALTER COLUMN type TYPE prizeeventtype "
        "USING type::text::prizeeventtype"
    )
    op.execute("DROP TYPE prizeeventtype_old")

    op.execute("ALTER TABLE prize_events ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE prizeeventstatus RENAME TO prizeeventstatus_old")
    op.execute("CREATE TYPE prizeeventstatus AS ENUM ('OPEN', 'RESOLVED')")
    op.execute(
        "ALTER TABLE prize_events ALTER COLUMN status TYPE prizeeventstatus "
        "USING status::text::prizeeventstatus"
    )
    op.execute("DROP TYPE prizeeventstatus_old")
    op.execute("ALTER TABLE prize_events ALTER COLUMN status SET DEFAULT 'OPEN'")


def downgrade() -> None:
    # No downgrade, same reasoning as cf3a1e425fa6: recreating the old (broken) casing would
    # just reintroduce the bug this migration exists to fix.
    raise NotImplementedError("downgrading would reintroduce the enum-casing bug")
