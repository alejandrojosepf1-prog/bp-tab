"""add new bet market types

Revision ID: cf3a1e425fa6
Revises: 647bf69f5a34
Create Date: 2026-07-23 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'cf3a1e425fa6'
down_revision: Union[str, None] = '647bf69f5a34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Purely additive: appends 3 labels to the existing `bettype` Postgres enum without
    # touching the 7 already there, so any BetMarket/Prediction row of an older bet_type
    # (top_n_break, top_n_speakers, head_to_head, breakout_team, best_institution) keeps
    # resolving exactly as before -- those types are just no longer offered for NEW markets
    # (see app.models.enums.BetType). Safe to run inside Alembic's transaction on Postgres 12+
    # (Neon) since none of these new values are referenced within this same migration.
    op.execute("ALTER TYPE bettype ADD VALUE IF NOT EXISTS 'ROUND_FULL_CALL'")
    op.execute("ALTER TYPE bettype ADD VALUE IF NOT EXISTS 'TOP_SPEAKER_POSITION'")
    op.execute("ALTER TYPE bettype ADD VALUE IF NOT EXISTS 'TEAM_BREAK'")


def downgrade() -> None:
    # Postgres cannot drop a single enum label without recreating the whole type (and
    # remapping every column that uses it) -- there is no safe, general-purpose downgrade here,
    # matching how this repo has never written a downgrade for enum-widening changes.
    raise NotImplementedError("removing enum values requires recreating the bettype type")
