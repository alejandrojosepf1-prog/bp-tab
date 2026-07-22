"""predictions entity_key: one open bet per entity, not per market

Revision ID: 807be8340337
Revises: cf3a1e425fa6
Create Date: 2026-07-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '807be8340337'
down_revision: Union[str, None] = 'cf3a1e425fa6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfilled to the "whole market" sentinel for every pre-existing row: the OLD unique
    # constraint (bet_market_id, user_id) already guaranteed at most one row per (market, user)
    # pair, so giving all of them the same constant entity_key can never introduce a collision
    # against the NEW constraint below -- this is a purely additive capability, not a data
    # migration that changes what any existing row means.
    op.add_column(
        "predictions",
        sa.Column("entity_key", sa.String(length=64), nullable=False, server_default="__market__"),
    )
    op.alter_column("predictions", "entity_key", server_default=None)

    op.drop_constraint("uq_predictions_market_user", "predictions", type_="unique")
    op.create_unique_constraint(
        "uq_predictions_market_user_entity",
        "predictions",
        ["bet_market_id", "user_id", "entity_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_predictions_market_user_entity", "predictions", type_="unique")
    # NOTE: if any user holds more than one prediction per market at this point (the whole
    # point of this migration), re-creating the old 2-column constraint here would fail with a
    # duplicate-key error -- there is no safe automatic downgrade past that state.
    op.create_unique_constraint(
        "uq_predictions_market_user", "predictions", ["bet_market_id", "user_id"]
    )
    op.drop_column("predictions", "entity_key")
