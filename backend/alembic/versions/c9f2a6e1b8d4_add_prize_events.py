"""add prize_events and prize_entries

Backs the admin "Premios" tab: manual token awards, raffles, and activity-participation
bonuses, independent of betting outcomes -- see app.services.prize_service.

Revision ID: c9f2a6e1b8d4
Revises: b7e1c4a9d302
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c9f2a6e1b8d4'
down_revision: Union[str, None] = 'b7e1c4a9d302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'prize_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'tournament_id',
            sa.Integer(),
            sa.ForeignKey('tournaments.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'type',
            sa.Enum('manual_award', 'raffle', 'activity_bonus', name='prizeeventtype'),
            nullable=False,
        ),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'status',
            sa.Enum('open', 'resolved', name='prizeeventstatus'),
            nullable=False,
            server_default='open',
        ),
        sa.Column('config', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('closes_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rng_seed', sa.String(length=100), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        'prize_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'prize_event_id',
            sa.Integer(),
            sa.ForeignKey('prize_events.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('tickets', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('awarded_amount', sa.Float(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint('prize_event_id', 'user_id', name='uq_prize_entries_event_user'),
    )


def downgrade() -> None:
    op.drop_table('prize_entries')
    op.drop_table('prize_events')
    op.execute('DROP TYPE IF EXISTS prizeeventtype')
    op.execute('DROP TYPE IF EXISTS prizeeventstatus')
