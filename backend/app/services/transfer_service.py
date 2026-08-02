"""P2P token transfers between users -- see app.models.transactions.Transaction.

Loans are explicitly out of scope here (see Active Priorities): this is transfer-only, with a
minimal ledger. Balance is moved synchronously and atomically within the caller's session/commit,
same pattern as betting_service.place_prediction.

Transfers move tokens within ONE tournament's `TournamentBalance` (CNADE 2026 Roadmap Pieza 3)
-- there's no such thing as a tournament-less transfer anymore, since balance itself is
per-tournament. A cap on transfer amount relative to that tournament's balance is deliberately
NOT implemented yet -- see Active Priorities: it's deferred until this per-tournament scoping
existed, which is exactly what this module just gained.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, User
from app.models.enums import TransactionType
from app.services.bankroll_service import get_or_create_tournament_balance

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
    tournament_id: int,
    *,
    note: str | None = None,
) -> tuple[Transaction, Transaction]:
    """Moves `amount` from `sender` to `recipient_id` within `tournament_id`'s TournamentBalance,
    writing one Transaction row per side. Raises TransferError on anything invalid; callers
    should roll back and not commit in that case, same convention as
    betting_service.place_prediction's InsufficientBalanceError."""
    if amount < MIN_TRANSFER_AMOUNT:
        raise TransferError(f"la transferencia mínima es {MIN_TRANSFER_AMOUNT:.0f} tokens")
    if recipient_id == sender.id:
        raise TransferError("no podés transferirte tokens a vos mismo")
    recipient = await session.get(User, recipient_id)
    if recipient is None:
        raise TransferError("destinatario no encontrado")
    if not recipient.is_active:
        raise TransferError("ese usuario no está activo")

    sender_balance = await get_or_create_tournament_balance(session, sender, tournament_id)
    recipient_balance = await get_or_create_tournament_balance(session, recipient, tournament_id)

    if sender_balance.balance < amount:
        raise TransferError(
            f"saldo insuficiente: tenés {sender_balance.balance:.2f}, necesitás {amount:.2f}"
        )

    sender_balance.balance -= amount
    recipient_balance.balance += amount

    out_tx = Transaction(
        user_id=sender.id,
        counterparty_user_id=recipient.id,
        type=TransactionType.TRANSFER_OUT,
        amount=amount,
        balance_after=sender_balance.balance,
        note=note,
    )
    in_tx = Transaction(
        user_id=recipient.id,
        counterparty_user_id=sender.id,
        type=TransactionType.TRANSFER_IN,
        amount=amount,
        balance_after=recipient_balance.balance,
        note=note,
    )
    session.add_all([out_tx, in_tx])
    await session.flush()
    return out_tx, in_tx
