"""Grant every account 100 play tokens instead of the old 1000 "fictional dollars".

Claim is a for-fun platform: balances are play tokens, never money. This drops the starting
grant to 100 and rebases EXISTING accounts onto the new scale so old and new users are
comparable -- rather than leaving early testers sitting on 10x everyone else's stack.

Rebasing rule: an account still untouched by betting (balance exactly at the old 1000.0 grant,
i.e. it never placed a bet) is simply reset to 100.0. An account that HAS bet is left alone --
its balance encodes real winnings/losses, and silently rewriting that would erase results the
leaderboard is derived from. See the downgrade note about why this is not reversible.

Revision ID: 640d59ae9d26
Revises: 807be8340337
Create Date: 2026-07-27 10:02:30.881549
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '640d59ae9d26'
down_revision: Union[str, None] = '807be8340337'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STARTING_BALANCE = 1000.0
NEW_STARTING_BALANCE = 100.0


def upgrade() -> None:
    op.alter_column(
        "users",
        "balance",
        existing_type=sa.Float(),
        existing_nullable=False,
        server_default=str(NEW_STARTING_BALANCE),
    )
    op.execute(
        sa.text("UPDATE users SET balance = :new WHERE balance = :old").bindparams(
            new=NEW_STARTING_BALANCE, old=OLD_STARTING_BALANCE
        )
    )


def downgrade() -> None:
    # Only the column default is restored. The balance rewrite above is NOT undone: after the
    # upgrade there's no way to tell a rebased account (100.0 because it never bet) apart from
    # one that legitimately played its way down to exactly 100.0, so reversing it would hand
    # tokens to people who lost them.
    op.alter_column(
        "users",
        "balance",
        existing_type=sa.Float(),
        existing_nullable=False,
        server_default=str(OLD_STARTING_BALANCE),
    )
