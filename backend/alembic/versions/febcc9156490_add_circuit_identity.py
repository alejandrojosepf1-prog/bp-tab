"""add circuit identity

Cross-tournament institution/person identity for the public circuit archive -- see
app.models.circuit's docstring and app.services.circuit_identity_service. Purely additive:
existing tournament-scoped tables (institutions, speakers, adjudicators) each get one nullable
FK pointing at the new identity tables, populated by ingestion going forward and by a separate
backfill pass for already-ingested tournaments. Nothing about existing rows/queries changes.

Revision ID: febcc9156490
Revises: 57f8f7530f8c
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'febcc9156490'
down_revision: Union[str, None] = '57f8f7530f8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'circuit_institutions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=300), nullable=False),
        sa.Column('slug', sa.String(length=300), nullable=False),
        sa.Column('region', sa.String(length=100), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_circuit_institutions_slug'), 'circuit_institutions', ['slug'], unique=True
    )

    op.create_table(
        'circuit_institution_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'circuit_institution_id',
            sa.Integer(),
            sa.ForeignKey('circuit_institutions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('alias', sa.String(length=300), nullable=False),
        sa.Column('confirmed', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alias', name='uq_circuit_institution_aliases_alias'),
    )
    op.create_index(
        op.f('ix_circuit_institution_aliases_circuit_institution_id'),
        'circuit_institution_aliases',
        ['circuit_institution_id'],
        unique=False,
    )

    op.create_table(
        'circuit_people',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=200), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_circuit_people_slug'), 'circuit_people', ['slug'], unique=True)

    op.create_table(
        'circuit_person_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'circuit_person_id',
            sa.Integer(),
            sa.ForeignKey('circuit_people.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('alias', sa.String(length=300), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alias', name='uq_circuit_person_aliases_alias'),
    )
    op.create_index(
        op.f('ix_circuit_person_aliases_circuit_person_id'),
        'circuit_person_aliases',
        ['circuit_person_id'],
        unique=False,
    )

    op.add_column(
        'institutions',
        sa.Column('circuit_institution_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_institutions_circuit_institution_id',
        'institutions',
        'circuit_institutions',
        ['circuit_institution_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_institutions_circuit_institution_id'),
        'institutions',
        ['circuit_institution_id'],
        unique=False,
    )

    op.add_column('speakers', sa.Column('circuit_person_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_speakers_circuit_person_id',
        'speakers',
        'circuit_people',
        ['circuit_person_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_speakers_circuit_person_id'), 'speakers', ['circuit_person_id'], unique=False
    )

    op.add_column('adjudicators', sa.Column('circuit_person_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_adjudicators_circuit_person_id',
        'adjudicators',
        'circuit_people',
        ['circuit_person_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_adjudicators_circuit_person_id'),
        'adjudicators',
        ['circuit_person_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_adjudicators_circuit_person_id'), table_name='adjudicators')
    op.drop_constraint('fk_adjudicators_circuit_person_id', 'adjudicators', type_='foreignkey')
    op.drop_column('adjudicators', 'circuit_person_id')

    op.drop_index(op.f('ix_speakers_circuit_person_id'), table_name='speakers')
    op.drop_constraint('fk_speakers_circuit_person_id', 'speakers', type_='foreignkey')
    op.drop_column('speakers', 'circuit_person_id')

    op.drop_index(op.f('ix_institutions_circuit_institution_id'), table_name='institutions')
    op.drop_constraint(
        'fk_institutions_circuit_institution_id', 'institutions', type_='foreignkey'
    )
    op.drop_column('institutions', 'circuit_institution_id')

    op.drop_index(
        op.f('ix_circuit_person_aliases_circuit_person_id'),
        table_name='circuit_person_aliases',
    )
    op.drop_table('circuit_person_aliases')

    op.drop_index(op.f('ix_circuit_people_slug'), table_name='circuit_people')
    op.drop_table('circuit_people')

    op.drop_index(
        op.f('ix_circuit_institution_aliases_circuit_institution_id'),
        table_name='circuit_institution_aliases',
    )
    op.drop_table('circuit_institution_aliases')

    op.drop_index(op.f('ix_circuit_institutions_slug'), table_name='circuit_institutions')
    op.drop_table('circuit_institutions')
