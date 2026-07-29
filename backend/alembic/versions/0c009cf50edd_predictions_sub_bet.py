"""Adds optional sub-bet (modular "apuesta específica" modifier) support to predictions.

A sub-bet is an extra, harder pick layered onto an EXISTING prediction (e.g. the exact rank gap
in a head-to-head, or the winning team's exact speaker points) -- never a separate market or a
separate row. The modifier detail itself lives in the existing `payload` JSON column
(`payload["sub_bet"]`, bet_type-specific shape); these three new columns give the sub-bet its
own independent lifecycle, distinct from the base pick's `odds`/`status`/`points_awarded`, since
some sub-bets (round_winner's speaker-points modifier) settle much later than the base pick they
ride along with -- see app.services.betting_service for the settlement rules.

All three are nullable and additive-only: every existing row gets NULL (no sub-bet), so this is
a pure schema addition with no backfill needed and no behavior change for predictions that never
use a sub-bet, matching the additive-migration style already used in this project (e.g.
807be8340337_predictions_entity_key.py, 640d59ae9d26_starting_balance_100_tokens.py).

`sub_bet_status` reuses the `predictionstatus` Postgres enum type the `status` column already
created -- create_type=False so this doesn't try to create it a second time.

Revision ID: 0c009cf50edd
Revises: 640d59ae9d26
Create Date: 2026-07-29 08:07:12.181002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0c009cf50edd'
down_revision: Union[str, None] = '640d59ae9d26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREDICTION_STATUS_ENUM = postgresql.ENUM(
    "OPEN", "LOCKED", "SETTLED", name="predictionstatus", create_type=False
)


def upgrade() -> None:
    op.add_column("predictions", sa.Column("sub_bet_odds", sa.Float(), nullable=True))
    op.add_column(
        "predictions",
        sa.Column("sub_bet_status", _PREDICTION_STATUS_ENUM, nullable=True),
    )
    op.add_column(
        "predictions", sa.Column("sub_bet_points_awarded", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("predictions", "sub_bet_points_awarded")
    op.drop_column("predictions", "sub_bet_status")
    op.drop_column("predictions", "sub_bet_odds")
