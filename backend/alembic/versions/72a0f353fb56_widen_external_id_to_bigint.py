"""widen external_id to bigint

Revision ID: 72a0f353fb56
Revises: 09d22d08e8d0
Create Date: 2026-07-20 08:20:50.744509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '72a0f353fb56'
down_revision: Union[str, None] = '09d22d08e8d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Debate.external_id sometimes holds a synthesized zlib.crc32(...) pseudo-id (elimination
    # rounds published without a public ballot -- see scraper/parsers.py's
    # _synthetic_debate_id), whose unsigned 32-bit output range exceeds Postgres's signed int32
    # max. Teams/Adjudicators never actually need more than int32 (their ids are always genuine
    # small Tabbycat ids), but widening all three keeps ExternalIdMixin's column type uniform.
    op.alter_column("teams", "external_id", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("adjudicators", "external_id", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("debates", "external_id", type_=sa.BigInteger(), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("debates", "external_id", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("adjudicators", "external_id", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("teams", "external_id", type_=sa.Integer(), existing_nullable=False)
