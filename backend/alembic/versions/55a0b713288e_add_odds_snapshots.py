"""add odds_snapshots

History table for the "evolución de cuotas" chart: one row per option per bet market, written on
a fixed cadence by app.services.odds_service.capture_odds_snapshot (see app.tasks.autoscrape).
Pure read history -- never touched by pricing or settlement.

Revision ID: 55a0b713288e
Revises: a3f8c1d2e5b7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '55a0b713288e'
down_revision: Union[str, None] = 'a3f8c1d2e5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'odds_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bet_market_id', sa.Integer(), nullable=False),
        sa.Column('option_key', sa.String(length=120), nullable=False),
        sa.Column('odds', sa.Float(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['bet_market_id'], ['bet_markets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_odds_snapshots_bet_market_id'), 'odds_snapshots', ['bet_market_id'], unique=False
    )
    op.create_index(
        op.f('ix_odds_snapshots_captured_at'), 'odds_snapshots', ['captured_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_odds_snapshots_captured_at'), table_name='odds_snapshots')
    op.drop_index(op.f('ix_odds_snapshots_bet_market_id'), table_name='odds_snapshots')
    op.drop_table('odds_snapshots')
