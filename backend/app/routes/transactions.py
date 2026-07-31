from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import TransactionSource, User
from ..schemas import TransactionCreate, TransactionOut

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("", response_model=TransactionOut)
async def create_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionOut:
    return TransactionOut(
        id=0,
        merchant=payload.merchant,
        amount=payload.amount,
        date=payload.date,
        source=TransactionSource.manual,
        is_anomaly=False,
        is_over_budget=False,
        created_at=datetime.utcnow(),
        owner_id=current_user.id,
        category_id=payload.category_id,
    )


@router.get("", response_model=list[TransactionOut])
async def list_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TransactionOut]:
    return [
        TransactionOut(
            id=1,
            merchant="Stub Coffee Co.",
            amount=4.50,
            date=date.today(),
            source=TransactionSource.manual,
            is_anomaly=False,
            is_over_budget=False,
            created_at=datetime.utcnow(),
            owner_id=current_user.id,
            category_id=None,
        )
    ]
