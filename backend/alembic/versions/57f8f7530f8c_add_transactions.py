"""add transactions

P2P token transfer ledger -- see app.models.transactions.Transaction. Enum labels are the Python
member NAMES (uppercase), matching the bettype/prizeeventtype(-fixed) convention -- see
a3f8c1d2e5b7's docstring for why lowercase values would break every insert.

Revision ID: 57f8f7530f8c
Revises: 34f0c0401c3b
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '57f8f7530f8c'
down_revision: Union[str, None] = '34f0c0401c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'counterparty_user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'type',
            sa.Enum('TRANSFER_OUT', 'TRANSFER_IN', name='transactiontype'),
            nullable=False,
        ),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('balance_after', sa.Float(), nullable=False),
        sa.Column('note', sa.String(length=280), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_transactions_user_id'), 'transactions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_transactions_user_id'), table_name='transactions')
    op.drop_table('transactions')
    op.execute('DROP TYPE IF EXISTS transactiontype')
