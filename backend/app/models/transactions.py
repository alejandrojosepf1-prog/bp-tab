from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import TransactionType
from app.models.mixins import TimestampMixin


class Transaction(Base, TimestampMixin):
    """P2P token transfer ledger row. A transfer writes ONE row per side (see TransactionType) so
    a user's full transfer history is `WHERE user_id = X`, no join needed. Scoped to transfers
    only for now -- stake/payout/prize balance changes still happen inline in betting_service/
    prize_service without a ledger row, same as before this feature (see Active Priorities' T5
    entry: a real ledger across ALL balance movement is a bigger, separate decision)."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable: rows written before CNADE 2026 Roadmap Pieza 3's P2P cap predate tournament-scoped
    # balances entirely, so there's no tournament to attribute them to. Every transfer from here
    # on sets it -- transfer_service sums this per (tournament_id, user_id) to enforce
    # MAX_P2P_RECEIVED_PER_TOURNAMENT.
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The other side of the transfer. Nullable + SET NULL so deleting a user (never actually
    # done today, but cheap to allow for) doesn't cascade-delete the counterparty's own row.
    counterparty_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[TransactionType] = mapped_column(nullable=False)
    # Always positive -- direction is TransactionType, not sign.
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # This user's balance immediately after this row, for an at-a-glance history without
    # recomputing a running total client-side.
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    counterparty = relationship("User", foreign_keys=[counterparty_user_id])
