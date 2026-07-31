from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas.transfers import TransactionOut, TransferCreate, TransferOut
from app.db.session import get_db
from app.models import Transaction, User
from app.services.transfer_service import TransferError, transfer_tokens

router = APIRouter(prefix="/transfers", tags=["transfers"])


def _to_transaction_out(tx: Transaction, counterparty_name: str | None) -> TransactionOut:
    out = TransactionOut.model_validate(tx)
    out.counterparty_display_name = counterparty_name
    return out


@router.post("", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    payload: TransferCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TransferOut:
    try:
        sent_tx, _received_tx = await transfer_tokens(
            session, current_user, payload.recipient_id, payload.amount, note=payload.note
        )
    except TransferError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    recipient = await session.get(User, payload.recipient_id)
    return TransferOut(
        sent=_to_transaction_out(sent_tx, recipient.display_name if recipient else None)
    )


@router.get("/me", response_model=list[TransactionOut])
async def my_transfers(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TransactionOut]:
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == current_user.id)
        .order_by(Transaction.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    counterparty_ids = {tx.counterparty_user_id for tx in rows if tx.counterparty_user_id}
    names: dict[int, str] = {}
    if counterparty_ids:
        users = (
            await session.execute(select(User).where(User.id.in_(counterparty_ids)))
        ).scalars()
        names = {u.id: u.display_name for u in users}
    return [
        _to_transaction_out(tx, names.get(tx.counterparty_user_id)) for tx in rows
    ]
