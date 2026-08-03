from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Anomaly, Budget, Category, Trace, Transaction, User
from ..schemas import AnomalyOut, BudgetCreate, BudgetOut, CategoryOut, TraceOut

router = APIRouter(tags=["data"])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Category]:
    result = await db.execute(select(Category).order_by(Category.name))
    return result.scalars().all()


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetOut]:
    result = await db.execute(
        select(Budget, Category.name)
        .join(Category, Budget.category_id == Category.id)
        .where(Budget.owner_id == current_user.id)
        .order_by(Category.name)
    )
    return [
        BudgetOut(
            id=budget.id,
            category_id=budget.category_id,
            category_name=category_name,
            monthly_limit=budget.monthly_limit,
        )
        for budget, category_name in result.all()
    ]


@router.post("/budgets", response_model=BudgetOut)
async def create_or_update_budget(
    payload: BudgetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BudgetOut:
    category = (
        await db.execute(select(Category).where(Category.id == payload.category_id))
    ).scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    existing = await db.execute(
        select(Budget).where(
            Budget.owner_id == current_user.id,
            Budget.category_id == payload.category_id,
        )
    )
    budget = existing.scalar_one_or_none()

    if budget is None:
        budget = Budget(
            owner_id=current_user.id,
            category_id=payload.category_id,
            monthly_limit=payload.monthly_limit,
        )
        db.add(budget)
    else:
        budget.monthly_limit = payload.monthly_limit

    await db.commit()
    await db.refresh(budget)

    return BudgetOut(
        id=budget.id,
        category_id=budget.category_id,
        category_name=category.name,
        monthly_limit=budget.monthly_limit,
    )


@router.get("/anomalies", response_model=list[AnomalyOut])
async def list_anomalies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AnomalyOut]:
    result = await db.execute(
        select(Anomaly, Transaction)
        .join(Transaction, Anomaly.transaction_id == Transaction.id)
        .where(Anomaly.owner_id == current_user.id)
        .order_by(Anomaly.flagged_at.desc())
    )
    return [
        AnomalyOut(
            id=anomaly.id,
            reason=anomaly.reason,
            flagged_at=anomaly.flagged_at,
            transaction_id=transaction.id,
            merchant=transaction.merchant,
            amount=transaction.amount,
            date=transaction.date,
        )
        for anomaly, transaction in result.all()
    ]


@router.get("/traces", response_model=list[TraceOut])
async def list_traces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Trace]:
    result = await db.execute(
        select(Trace)
        .where(Trace.owner_id == current_user.id)
        .order_by(Trace.created_at.desc())
        .limit(20)
    )
    return result.scalars().all()
