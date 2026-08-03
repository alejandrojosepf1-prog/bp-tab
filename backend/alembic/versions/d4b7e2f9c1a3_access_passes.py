"""add access_passes and tournaments.requires_access_pass

CNADE 2026 Roadmap Pieza 4: pass-based betting access per tournament, admin-toggled and
defaulting off so no existing or trial tournament is affected until an admin turns it on.

Revision ID: d4b7e2f9c1a3
Revises: c8f3a91d5e6b
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd4b7e2f9c1a3'
down_revision: Union[str, None] = 'c8f3a91d5e6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tournaments',
        sa.Column(
            'requires_access_pass', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )

    op.create_table(
        'access_passes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'tournament_id',
            sa.Integer(),
            sa.ForeignKey('tournaments.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('email', sa.String(length=255), nullable=False, index=True),
        sa.Column('phone', sa.String(length=50), nullable=False),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'approved', 'rejected', name='accesspassstatus'),
            nullable=False,
            server_default='pending',
        ),
        sa.Column('match_hint', sa.JSON(), nullable=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
            index=True,
        ),
        sa.Column(
            'reviewed_by_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint('tournament_id', 'email', name='uq_access_passes_tournament_email'),
    )


def downgrade() -> None:
    op.drop_table('access_passes')
    op.execute('DROP TYPE IF EXISTS accesspassstatus')
    op.drop_column('tournaments', 'requires_access_pass')
