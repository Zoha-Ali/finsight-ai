from datetime import date
from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import and_, extract, func, not_, select

from .database import AsyncSessionLocal
from .models import Anomaly, Budget, Category, Transaction, TransactionSource

mcp = FastMCP("finsight-ai")


@mcp.tool()
async def get_transactions(owner_id: int, limit: int = 50) -> list[dict]:
    """Return a user's most recent transactions, newest first.

    Use this to answer questions about what a user has spent money on,
    to list recent purchases, or to pull raw transaction data before
    running categorization, anomaly detection, or forecasting.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction)
            .where(Transaction.owner_id == owner_id)
            .order_by(Transaction.date.desc(), Transaction.created_at.desc())
            .limit(limit)
        )
        transactions = result.scalars().all()
        return [
            {
                "id": t.id,
                "merchant": t.merchant,
                "amount": t.amount,
                "date": t.date.isoformat(),
                "source": t.source.value,
                "is_anomaly": t.is_anomaly,
                "is_over_budget": t.is_over_budget,
                "category_id": t.category_id,
            }
            for t in transactions
        ]


@mcp.tool()
async def record_transaction(
    owner_id: int,
    merchant: str,
    amount: float,
    category_id: Optional[int] = None,
) -> dict:
    """Create a new manually-entered transaction for a user.

    Use this when a user tells the assistant about a purchase directly
    (not via a receipt upload). Always records the transaction as
    source="manual" and dated today.
    """
    async with AsyncSessionLocal() as session:
        transaction = Transaction(
            owner_id=owner_id,
            merchant=merchant,
            amount=amount,
            date=date.today(),
            source=TransactionSource.manual,
            category_id=category_id,
        )
        session.add(transaction)
        await session.commit()
        await session.refresh(transaction)
        return {
            "id": transaction.id,
            "merchant": transaction.merchant,
            "amount": transaction.amount,
            "date": transaction.date.isoformat(),
            "source": transaction.source.value,
            "category_id": transaction.category_id,
        }


@mcp.tool()
async def get_budget(owner_id: int, category_id: int) -> Optional[dict]:
    """Return a user's monthly budget limit for a specific category.

    Returns None if no budget has been configured for that user and
    category. Use this before deciding whether a transaction pushes
    the user over budget.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.owner_id == owner_id,
                Budget.category_id == category_id,
            )
        )
        budget = result.scalar_one_or_none()
        if budget is None:
            return None
        return {
            "id": budget.id,
            "monthly_limit": budget.monthly_limit,
            "category_id": budget.category_id,
        }


@mcp.tool()
async def get_monthly_summary(owner_id: int, month: int, year: int) -> list[dict]:
    """Return a user's total spending grouped by category for one month.

    Use this to answer questions like "how much did I spend on food in
    June" or to build the category breakdown a forecast is based on.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                Transaction.category_id,
                Category.name,
                func.sum(Transaction.amount).label("total_spent"),
            )
            .outerjoin(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.owner_id == owner_id,
                extract("month", Transaction.date) == month,
                extract("year", Transaction.date) == year,
            )
            .group_by(Transaction.category_id, Category.name)
        )
        return [
            {
                "category_id": category_id,
                "category_name": category_name,
                "total_spent": float(total_spent),
            }
            for category_id, category_name, total_spent in result.all()
        ]


@mcp.tool()
async def get_historical_monthly_average(
    owner_id: int,
    category_id: int,
    exclude_month: int,
    exclude_year: int,
) -> Optional[dict]:
    """Return a user's average monthly spending in a category from past
    months, excluding one specific month/year (typically the current,
    still-in-progress month, since it isn't over yet and would skew the
    average low).

    Returns None if there's no prior spending in that category at all.
    Use this as a fallback baseline for forecasting when the user hasn't
    set an explicit budget for a category.
    """
    async with AsyncSessionLocal() as session:
        month_expr = extract("month", Transaction.date)
        year_expr = extract("year", Transaction.date)

        monthly_totals = (
            select(func.sum(Transaction.amount).label("monthly_total"))
            .where(
                Transaction.owner_id == owner_id,
                Transaction.category_id == category_id,
                not_(and_(month_expr == exclude_month, year_expr == exclude_year)),
            )
            .group_by(year_expr, month_expr)
        ).subquery()

        result = await session.execute(
            select(func.avg(monthly_totals.c.monthly_total), func.count()).select_from(monthly_totals)
        )
        average, months_counted = result.one()

        if average is None or months_counted == 0:
            return None

        return {"average_monthly_spend": float(average), "months_counted": months_counted}


@mcp.tool()
async def get_anomalies(owner_id: int, limit: int = 20) -> list[dict]:
    """Return a user's most recently flagged anomalies, newest first.

    Each result includes the linked transaction's merchant, amount, and
    date. Use this to answer questions about unusual spending or to
    summarize what's currently flagged as suspicious.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Anomaly, Transaction)
            .join(Transaction, Anomaly.transaction_id == Transaction.id)
            .where(Anomaly.owner_id == owner_id)
            .order_by(Anomaly.flagged_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": anomaly.id,
                "reason": anomaly.reason,
                "flagged_at": anomaly.flagged_at.isoformat(),
                "transaction_id": transaction.id,
                "merchant": transaction.merchant,
                "amount": transaction.amount,
                "date": transaction.date.isoformat(),
            }
            for anomaly, transaction in result.all()
        ]


if __name__ == "__main__":
    mcp.run()
