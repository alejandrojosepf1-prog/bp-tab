"""P2P token transfers between users -- see app.models.transactions.Transaction.

Loans are explicitly out of scope here (see Active Priorities): this is transfer-only, with a
minimal ledger. Balance is moved synchronously and atomically within the caller's session/commit,
same pattern as betting_service.place_prediction.

Transfers move tokens within ONE tournament's `TournamentBalance` (CNADE 2026 Roadmap Pieza 3)
-- there's no such thing as a tournament-less transfer anymore, since balance itself is
per-tournament.

**Anti-collusion cap (closed 2026-08-02):** the leaderboard's `total_points` is settled-prediction
net profit, not raw balance -- but a bigger balance still buys bigger absolute stakes, so one
account gifting tokens to another right before a confident bet can inflate that second account's
absolute net profit without any extra skill. `MAX_P2P_RECEIVED_PER_TOURNAMENT` caps how much a
user can RECEIVE via P2P in one tournament, cumulative across every sender -- not a per-transfer
cap, which a determined pair could just work around with several smaller transfers. A transfer
that would push the recipient over the cap is rejected whole, same as insufficient balance --
never silently trimmed to what still fits.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, User
from app.models.betting import STARTING_BALANCE
from app.models.enums import TransactionType
from app.services.bankroll_service import get_or_create_tournament_balance

# Anti-spam floor, not an anti-exploit measure (unlike MOTION_TYPE_MIN_STAKE) -- there's no
# arbitrage in moving your own tokens to a friend, just no reason to ledger a 0.01-token transfer.
MIN_TRANSFER_AMOUNT = 1.0

# One full starting grant, gifted -- a memorable ceiling tied to an existing constant rather
# than a new magic number. See the module docstring for why this is per-tournament-received,
# not per-transfer.
MAX_P2P_RECEIVED_PER_TOURNAMENT = STARTING_BALANCE


async def _received_this_tournament(session: AsyncSession, user_id: int, tournament_id: int) -> float:
    stmt = select(func.coalesce(func.sum(Transaction.amount), 0.0)).where(
        Transaction.user_id == user_id,
        Transaction.tournament_id == tournament_id,
        Transaction.type == TransactionType.TRANSFER_IN,
    )
    return float((await session.execute(stmt)).scalar_one())


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

    already_received = await _received_this_tournament(session, recipient.id, tournament_id)
    if already_received + amount > MAX_P2P_RECEIVED_PER_TOURNAMENT:
        raise TransferError(
            f"ese usuario ya recibió {already_received:.2f} de "
            f"{MAX_P2P_RECEIVED_PER_TOURNAMENT:.0f} tokens permitidos por transferencias en "
            "este torneo"
        )

    sender_balance.balance -= amount
    recipient_balance.balance += amount

    out_tx = Transaction(
        tournament_id=tournament_id,
        user_id=sender.id,
        counterparty_user_id=recipient.id,
        type=TransactionType.TRANSFER_OUT,
        amount=amount,
        balance_after=sender_balance.balance,
        note=note,
    )
    in_tx = Transaction(
        tournament_id=tournament_id,
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
