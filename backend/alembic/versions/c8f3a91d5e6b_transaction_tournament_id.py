"""add nullable tournament_id to transactions

CNADE 2026 Roadmap Pieza 3 (P2P cap): transfer_service needs to sum how much a user has
already RECEIVED via P2P within one tournament, to enforce the anti-collusion cap. Existing
transaction rows predate tournament-scoped balances entirely -- there's no tournament to
attribute them to, so the column stays NULL for them (they were global-wallet transfers, not
scoped to any tournament's cap) and populated for every transfer from here on.

Revision ID: c8f3a91d5e6b
Revises: a1c4e9f27b60
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c8f3a91d5e6b'
down_revision: Union[str, None] = 'a1c4e9f27b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'transactions',
        sa.Column(
            'tournament_id',
            sa.Integer(),
            sa.ForeignKey('tournaments.id', ondelete='CASCADE'),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_transactions_tournament_id', 'transactions', ['tournament_id']
    )


def downgrade() -> None:
    op.drop_index('ix_transactions_tournament_id', table_name='transactions')
    op.drop_column('transactions', 'tournament_id')
