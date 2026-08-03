import os

import httpx
from dotenv import load_dotenv
from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..mcp_server import get_transactions
from ..models import Anomaly, Category, Transaction
from .tracing import save_trace

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-haiku-4-5"

CATEGORIES = ["food", "transport", "shopping", "entertainment", "bills", "health", "other"]

ANOMALY_MULTIPLIER = 2.5


async def _predict_category(merchant: str, amount: float) -> str:
    """Ask claude-haiku-4-5 to pick a category, over a raw HTTP call.

    This bypasses the anthropic SDK on purpose: the SDK's jiter dependency
    has previously been blocked by Windows Application Control on this
    project's dev machines, so agent code talks to the Messages API
    directly via httpx instead of depending on the SDK being importable.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    prompt = (
        "Classify this transaction into exactly one category from this "
        f"list: {', '.join(CATEGORIES)}.\n\n"
        f"Merchant: {merchant}\n"
        f"Amount: ${amount:.2f}\n\n"
        "Respond with only the category name, lowercase, and nothing else."
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()

    predicted = data["content"][0]["text"].strip().lower()
    return predicted if predicted in CATEGORIES else "other"


async def categorize_transaction(transaction_id: int, owner_id: int) -> dict:
    """Categorize a transaction and flag it as an anomaly if it stands out.

    Predicts a category with claude-haiku-4-5, compares the transaction's
    amount against the user's average spend in that category (computed in
    Python from MCP's get_transactions, not by the LLM), and flags it as
    an anomaly if it's more than 2.5x that average. Updates the
    transaction's category_id directly and, if flagged, writes an Anomaly
    row with the reason.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.owner_id == owner_id,
            )
        )
        transaction = result.scalar_one_or_none()
        if transaction is None:
            raise ValueError(f"Transaction {transaction_id} not found for owner {owner_id}")

        predicted_category = await _predict_category(transaction.merchant, transaction.amount)

        category_result = await session.execute(
            select(Category).where(Category.name == predicted_category)
        )
        category = category_result.scalar_one_or_none()
        if category is None:
            category = Category(name=predicted_category)
            session.add(category)
            await session.flush()

        recent_transactions = await get_transactions(owner_id=owner_id, limit=100)
        same_category_amounts = [
            t["amount"]
            for t in recent_transactions
            if t["category_id"] == category.id and t["id"] != transaction.id
        ]

        is_anomaly = False
        reason = None
        if same_category_amounts:
            average = sum(same_category_amounts) / len(same_category_amounts)
            if average > 0 and transaction.amount > ANOMALY_MULTIPLIER * average:
                is_anomaly = True
                reason = (
                    f"Amount ${transaction.amount:.2f} is "
                    f"{transaction.amount / average:.1f}x the average "
                    f"(${average:.2f}) of the user's last "
                    f"{len(same_category_amounts)} '{predicted_category}' transactions."
                )

        transaction.category_id = category.id
        transaction.is_anomaly = is_anomaly

        if is_anomaly:
            existing_anomaly = await session.execute(
                select(Anomaly).where(Anomaly.transaction_id == transaction.id)
            )
            anomaly = existing_anomaly.scalar_one_or_none()
            if anomaly is None:
                session.add(
                    Anomaly(
                        owner_id=owner_id,
                        transaction_id=transaction.id,
                        reason=reason,
                    )
                )
            else:
                anomaly.reason = reason

        await session.commit()

        result = {
            "transaction_id": transaction.id,
            "category": predicted_category,
            "category_id": category.id,
            "is_anomaly": is_anomaly,
            "reason": reason,
        }

    await save_trace(
        owner_id,
        f"Categorize transaction {transaction_id}",
        "categorization",
        [{"agent": "categorization_agent", "action": "categorize_transaction", "result": result}],
    )

    return result
