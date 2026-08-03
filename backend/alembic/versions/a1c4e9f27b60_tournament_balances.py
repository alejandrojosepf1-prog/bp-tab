"""add tournament_balances, drop users.balance

CNADE 2026 Roadmap Pieza 3: a play-token balance is 100% per-tournament now, not one wallet
shared across every tournament (see app.models.betting.TournamentBalance and
app.services.bankroll_service).

Data migration: for every user, their current `users.balance` is carried into a
TournamentBalance row scoped to the tournament of their MOST RECENT prediction (the only
economic activity that's tournament-scoped today -- P2P transfers/prizes have no tournament
link before this migration). A user with no predictions at all gets no row here; their first
real tournament balance is lazily created on demand by `bankroll_service`, same as any brand
new user. This is lossless for the only real-money history that has ever existed on this
platform (CMUDE 2026) -- see the vault note "Bankroll por torneo (Pieza 3)" for why preserving
this matters: it's the exact input the ROI-carryover formula needs for a user's NEXT tournament.

Revision ID: a1c4e9f27b60
Revises: febcc9156490
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1c4e9f27b60'
down_revision: Union[str, None] = 'febcc9156490'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tournament_balances',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'tournament_id',
            sa.Integer(),
            sa.ForeignKey('tournaments.id', ondelete='CASCADE'),
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
        sa.Column('balance', sa.Float(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            'tournament_id', 'user_id', name='uq_tournament_balances_tournament_user'
        ),
    )

    # One row per user: their balance, scoped to the tournament of their most recent prediction.
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_balances (tournament_id, user_id, balance, created_at, updated_at)
            SELECT last_activity.tournament_id, u.id, u.balance, now(), now()
            FROM users u
            JOIN LATERAL (
                SELECT bm.tournament_id
                FROM predictions p
                JOIN bet_markets bm ON bm.id = p.bet_market_id
                WHERE p.user_id = u.id
                ORDER BY p.locked_at DESC
                LIMIT 1
            ) AS last_activity ON true
            """
        )
    )

    op.drop_column('users', 'balance')


def downgrade() -> None:
    # The reverse mapping is lossy for any user with predictions in more than one tournament
    # (each row's balance is a fraction of a wallet that no longer exists as a single number)
    # -- restore the column with the platform's flat starting grant and let a future migration
    # decide what, if anything, to backfill.
    op.add_column(
        'users', sa.Column('balance', sa.Float(), nullable=False, server_default='100.0')
    )
    op.drop_table('tournament_balances')
