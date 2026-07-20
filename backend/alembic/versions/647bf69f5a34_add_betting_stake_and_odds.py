"""add betting stake and odds

Revision ID: 647bf69f5a34
Revises: 72a0f353fb56
Create Date: 2026-07-20 10:16:05.110369

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '647bf69f5a34'
down_revision: Union[str, None] = '72a0f353fb56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("balance", sa.Float(), nullable=False, server_default="1000.0")
    )
    op.alter_column("users", "balance", server_default=None)

    # server_default here backfills any prediction placed before the stake/odds model existed
    # (harmless: stake_amount=0 means a settlement of that row pays out $0 either way).
    op.add_column(
        "predictions", sa.Column("stake_amount", sa.Float(), nullable=False, server_default="0.0")
    )
    op.alter_column("predictions", "stake_amount", server_default=None)
    op.add_column(
        "predictions", sa.Column("odds", sa.Float(), nullable=False, server_default="1.0")
    )
    op.alter_column("predictions", "odds", server_default=None)


def downgrade() -> None:
    op.drop_column("predictions", "odds")
    op.drop_column("predictions", "stake_amount")
    op.drop_column("users", "balance")
