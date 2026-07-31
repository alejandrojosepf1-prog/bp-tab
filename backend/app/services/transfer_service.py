"""P2P token transfers between users -- see app.models.transactions.Transaction.

Loans are explicitly out of scope here (see Active Priorities): this is transfer-only, with a
minimal ledger. Balance is moved synchronously and atomically within the caller's session/commit,
same pattern as betting_service.place_prediction.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, User
from app.models.enums import TransactionType

# Anti-spam floor, not an anti-exploit measure (unlike MOTION_TYPE_MIN_STAKE) -- there's no
# arbitrage in moving your own tokens to a friend, just no reason to ledger a 0.01-token transfer.
MIN_TRANSFER_AMOUNT = 1.0


class TransferError(Exception):
    """Raised for any invalid transfer -- the router maps this to a 400."""


async def transfer_tokens(
    session: AsyncSession,
    sender: User,
    recipient_id: int,
    amount: float,
    *,
    note: str | None = None,
) -> tuple[Transaction, Transaction]:
    """Moves `amount` from `sender` to `recipient_id`, writing one Transaction row per side.
    Raises TransferError on anything invalid; callers should roll back and not commit in that
    case, same convention as betting_service.place_prediction's InsufficientBalanceError."""
    if amount < MIN_TRANSFER_AMOUNT:
        raise TransferError(f"la transferencia mínima es {MIN_TRANSFER_AMOUNT:.0f} tokens")
    if recipient_id == sender.id:
        raise TransferError("no podés transferirte tokens a vos mismo")
    recipient = await session.get(User, recipient_id)
    if recipient is None:
        raise TransferError("destinatario no encontrado")
    if not recipient.is_active:
        raise TransferError("ese usuario no está activo")
    if sender.balance < amount:
        raise TransferError(
            f"saldo insuficiente: tenés {sender.balance:.2f}, necesitás {amount:.2f}"
        )

    sender.balance -= amount
    recipient.balance += amount

    out_tx = Transaction(
        user_id=sender.id,
        counterparty_user_id=recipient.id,
        type=TransactionType.TRANSFER_OUT,
        amount=amount,
        balance_after=sender.balance,
        note=note,
    )
    in_tx = Transaction(
        user_id=recipient.id,
        counterparty_user_id=sender.id,
        type=TransactionType.TRANSFER_IN,
        amount=amount,
        balance_after=recipient.balance,
        note=note,
    )
    session.add_all([out_tx, in_tx])
    await session.flush()
    return out_tx, in_tx
