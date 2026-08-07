from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.categorization_agent import categorize_transaction
from ..auth import get_current_user
from ..database import get_db
from ..models import Anomaly, Category, Transaction, TransactionSource, User
from ..schemas import TransactionCreate, TransactionOut

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _to_transaction_out(transaction: Transaction, category_name: str | None) -> TransactionOut:
    return TransactionOut(
        id=transaction.id,
        merchant=transaction.merchant,
        amount=transaction.amount,
        date=transaction.date,
        date_estimated=transaction.date_estimated,
        source=transaction.source,
        is_anomaly=transaction.is_anomaly,
        is_over_budget=transaction.is_over_budget,
        categorized_by_model=transaction.categorized_by_model,
        created_at=transaction.created_at,
        owner_id=transaction.owner_id,
        category_id=transaction.category_id,
        category_name=category_name,
    )


@router.post("", response_model=TransactionOut)
async def create_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionOut:
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

    category_name = None
    if transaction.category_id is not None:
        category_name = (
            await db.execute(select(Category.name).where(Category.id == transaction.category_id))
        ).scalar_one_or_none()

    return _to_transaction_out(transaction, category_name)


@router.get("", response_model=list[TransactionOut])
async def list_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TransactionOut]:
    result = await db.execute(
        select(Transaction, Category.name)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(Transaction.owner_id == current_user.id)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
    )
    return [_to_transaction_out(transaction, category_name) for transaction, category_name in result.all()]


@router.patch("/{transaction_id}/approve", response_model=TransactionOut)
async def approve_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionOut:
    """Dismiss a flagged anomaly: mark the transaction as reviewed/normal
    without deleting it.

    Scoped by owner_id in the same SELECT (not a separate ownership check
    after fetching) so a transaction_id belonging to another user 404s
    exactly like a nonexistent one - it doesn't leak whether the ID exists.
    The linked Anomaly row is deleted outright rather than flagged
    "resolved": this mirrors delete_transaction's own cleanup (which
    already deletes any Anomaly row for a removed transaction) and matches
    how anomalies are treated everywhere else in this codebase - purely as
    a live flag on the transaction, not as an audit trail. Anomaly has no
    "resolved" field or history-keeping precedent to extend, so adding one
    here would be a new pattern rather than a consistent one.
    """
    transaction = (
        await db.execute(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.owner_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    if not transaction.is_anomaly:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction is not flagged as an anomaly",
        )

    transaction.is_anomaly = False
    await db.execute(delete(Anomaly).where(Anomaly.transaction_id == transaction_id))
    await db.commit()
    await db.refresh(transaction)

    category_name = None
    if transaction.category_id is not None:
        category_name = (
            await db.execute(select(Category.name).where(Category.id == transaction.category_id))
        ).scalar_one_or_none()

    return _to_transaction_out(transaction, category_name)


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
