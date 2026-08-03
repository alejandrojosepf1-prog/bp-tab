"""add tournaments.year and results.video_url

CNADE 2026 Roadmap Pieza 2: public circuit archive. `year` lets backfilled historical
tournaments (CMUDE 2018-2025) be browsed chronologically without relying on created_at,
which is scrape/insert time, not when the tournament happened. `video_url` is the
admin-entered "watch this debate" link on Result.

Revision ID: e5a9c2f18b4d
Revises: d4b7e2f9c1a3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e5a9c2f18b4d'
down_revision: Union[str, None] = 'd4b7e2f9c1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tournaments', sa.Column('year', sa.Integer(), nullable=True))
    op.add_column('results', sa.Column('video_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('results', 'video_url')
    op.drop_column('tournaments', 'year')
