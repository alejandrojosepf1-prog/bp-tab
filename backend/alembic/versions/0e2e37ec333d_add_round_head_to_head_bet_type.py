"""add_round_head_to_head_bet_type

Purely additive: appends 1 label to the existing `bettype` Postgres enum without touching any
already there -- see cf3a1e425fa6_add_new_bet_market_types.py for the identical pattern this
follows. Safe to run inside Alembic's transaction on Postgres 12+ (Neon) since the new value
isn't referenced within this same migration.

Revision ID: 0e2e37ec333d
Revises: 0c009cf50edd
Create Date: 2026-07-29 08:10:09.300966
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0e2e37ec333d'
down_revision: Union[str, None] = '0c009cf50edd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE bettype ADD VALUE IF NOT EXISTS 'ROUND_HEAD_TO_HEAD'")


def downgrade() -> None:
    # Postgres cannot drop a single enum label without recreating the whole type (and
    # remapping every column that uses it) -- there is no safe, general-purpose downgrade here,
    # matching how this repo has never written a downgrade for enum-widening changes.
    raise NotImplementedError("removing enum values requires recreating the bettype type")
