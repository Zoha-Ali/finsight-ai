from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.categorization_agent import categorize_transaction
from ..auth import get_current_user
from ..database import get_db
from ..models import Anomaly, Transaction, TransactionSource, User
from ..schemas import TransactionCreate, TransactionOut

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("", response_model=TransactionOut)
async def create_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Transaction:
    transaction = Transaction(
        owner_id=current_user.id,
        merchant=payload.merchant,
        amount=payload.amount,
        date=payload.date,
        source=TransactionSource.manual,
        category_id=payload.category_id,
    )
    db.add(transaction)
    await db.commit()
    await db.refresh(transaction)

    await categorize_transaction(transaction.id, current_user.id)
    await db.refresh(transaction)

    return transaction


@router.get("", response_model=list[TransactionOut])
async def list_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Transaction]:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.owner_id == current_user.id)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    transaction = (
        await db.execute(select(Transaction).where(Transaction.id == transaction_id))
    ).scalar_one_or_none()

    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    if transaction.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this transaction",
        )

    await db.execute(delete(Anomaly).where(Anomaly.transaction_id == transaction_id))
    await db.delete(transaction)
    await db.commit()
