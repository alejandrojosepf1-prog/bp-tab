"""add round motion_text and info_slide

Mirrors the tournament's public /motions/ page onto Round so the betting UI can show what is
actually being debated. Distinct from results.motion_text, which is per-debate and only lands
once a ballot is published -- i.e. after the debate is already over.

Revision ID: b7e1c4a9d302
Revises: 0e2e37ec333d
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b7e1c4a9d302'
down_revision: Union[str, None] = '0e2e37ec333d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('rounds', sa.Column('motion_text', sa.Text(), nullable=True))
    op.add_column('rounds', sa.Column('info_slide', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('rounds', 'info_slide')
    op.drop_column('rounds', 'motion_text')
