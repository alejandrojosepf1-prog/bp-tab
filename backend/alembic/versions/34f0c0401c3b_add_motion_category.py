"""add motion_category to rounds and motion_type to bettype

Backs the "Tipo de moción" bet market: admins load the round's real MotionCategory before the
motion is revealed (see app.api.routers.admin), and MOTION_TYPE predictions guess it.

IMPORTANT: Postgres enum labels for MotionCategory must be the Python enum MEMBER NAMES
(uppercase), not their lowercase `.value` strings -- SQLAlchemy's default Enum type binds by
member name. Getting this backwards is exactly the bug fixed by a3f8c1d2e5b7 (prize_events
casing, broke every prize event creation in production); this migration follows the corrected
`bettype`-style convention (see cf3a1e425fa6) instead of repeating it.

Revision ID: 34f0c0401c3b
Revises: 55a0b713288e
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '34f0c0401c3b'
down_revision: Union[str, None] = '55a0b713288e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    motion_category = sa.Enum(
        'POLICY',
        'POLICY_SHOULD',
        'VALUE_JUDGMENT',
        'SUPPORT_OPPOSE',
        'REGRET',
        'PREFERENCE',
        'PREDICTION',
        'HOPE',
        'ACTOR',
        name='motioncategory',
    )
    motion_category.create(op.get_bind())
    op.add_column('rounds', sa.Column('motion_category', motion_category, nullable=True))

    # Purely additive to the existing `bettype` enum, same as cf3a1e425fa6 -- safe inside
    # Alembic's transaction on Postgres 12+ (Neon) since MOTION_TYPE isn't referenced within
    # this same migration.
    op.execute("ALTER TYPE bettype ADD VALUE IF NOT EXISTS 'MOTION_TYPE'")


def downgrade() -> None:
    op.drop_column('rounds', 'motion_category')
    op.execute('DROP TYPE IF EXISTS motioncategory')
    # bettype's MOTION_TYPE label is NOT removed -- same reasoning as cf3a1e425fa6's downgrade:
    # Postgres cannot drop a single enum label without recreating the whole type.
