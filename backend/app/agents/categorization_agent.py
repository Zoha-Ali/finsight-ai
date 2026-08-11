import os
from datetime import date
from typing import Optional

import httpx
from dotenv import load_dotenv
from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..groq_client import call_groq, is_groq_model
from ..mcp_server import get_transactions, get_weekly_average
from ..models import Anomaly, Category, Transaction
from .tracing import save_trace

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-haiku-4-5"

CATEGORIES = ["food", "transport", "shopping", "entertainment", "bills", "health", "other"]

ANOMALY_MULTIPLIER = 2.5


async def _call_prediction_model(messages: list[dict], model: str) -> str:
    """Send a plain (non-tool-use) chat message and return the raw text.

    This bypasses the anthropic SDK on purpose: the SDK's jiter dependency
    has previously been blocked by Windows Application Control on this
    project's dev machines, so agent code talks to the Messages API
    directly via httpx instead of depending on the SDK being importable.
    Routed to Groq instead when `model` is the Groq model (see
    supervisor_agent.py's simple/complex classification, which sends
    "simple" categorization requests here). Since this call never uses
    tools, a plain role/content message list works unchanged against
    either provider's API, so the two branches only differ in which HTTP
    call they make.
    """
    if is_groq_model(model):
        data = await call_groq(messages, model=model, max_tokens=16)
        return data["choices"][0]["message"]["content"].strip()

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 16,
                "messages": messages,
            },
        )
        response.raise_for_status()
        data = response.json()

    return "".join(block["text"] for block in data["content"] if block.get("type") == "text").strip()


async def _predict_category(merchant: str, amount: float, model: str = MODEL) -> str:
    """Ask a model to pick a category, retrying once if it doesn't return
    one of the allowed category names (same retry-once-then-fall-back
    pattern used for JSON extraction in receipt_agent.py, adapted for a
    plain-text single-token response instead of a JSON object).
    """
    prompt = (
        "Classify this transaction into exactly one category from this "
        f"list: {', '.join(CATEGORIES)}.\n\n"
        f"Merchant: {merchant}\n"
        f"Amount: Rs. {amount:.2f}\n\n"
        "Respond with only the category name, lowercase, and nothing else."
    )
    messages: list[dict] = [{"role": "user", "content": prompt}]

    for attempt in range(2):
        raw_text = await _call_prediction_model(messages, model)
        predicted = raw_text.strip().lower()
        if predicted in CATEGORIES:
            return predicted

        if attempt == 0:
            messages.append({"role": "assistant", "content": raw_text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f'"{raw_text}" is not one of the allowed categories. Respond again with '
                        f"ONLY one of these exact words, lowercase, nothing else: {', '.join(CATEGORIES)}."
                    ),
                }
            )

    # Still not a recognized category after a retry - fall back rather
    # than crash the whole transaction-creation flow over a formatting slip.
    return "other"


async def _get_anomaly_baseline(
    owner_id: int, category_id: int, transaction_date: date, exclude_transaction_id: int
) -> tuple[Optional[float], str]:
    """Return (average, description) to compare a transaction's amount
    against for anomaly detection.

    Prefers the user's average weekly spending in this category (a
    transaction that's a large multiple of a typical week's total is a
    more meaningful signal than comparing against individual past
    transaction amounts). Falls back to the average of the user's recent
    same-category transactions - the previous approach - when there's no
    distinct prior week of spending yet (e.g. a brand new category),
    so a new category still gets some anomaly protection instead of none.
    Returns (None, "") if there's no baseline data of either kind.
    """
    iso_year, iso_week, _ = transaction_date.isocalendar()
    weekly = await get_weekly_average(
        owner_id=owner_id,
        category_id=category_id,
        exclude_week=iso_week,
        exclude_isoyear=iso_year,
    )
    if weekly is not None and weekly["average_weekly_spend"] > 0:
        weeks = weekly["weeks_counted"]
        description = (
            f"Rs. {weekly['average_weekly_spend']:.2f}/week average spend in this "
            f"category across {weeks} prior week{'s' if weeks != 1 else ''}"
        )
        return weekly["average_weekly_spend"], description

    recent_transactions = await get_transactions(owner_id=owner_id, limit=100)
    same_category_amounts = [
        t["amount"]
        for t in recent_transactions
        if t["category_id"] == category_id and t["id"] != exclude_transaction_id
    ]
    if not same_category_amounts:
        return None, ""

    average = sum(same_category_amounts) / len(same_category_amounts)
    description = (
        f"Rs. {average:.2f} average of the user's last {len(same_category_amounts)} "
        "transactions in this category"
    )
    return average, description


async def categorize_transaction(transaction_id: int, owner_id: int, model: str = MODEL) -> dict:
    """Categorize a transaction and flag it as an anomaly if it stands out.

    Predicts a category with `model` (defaults to this module's standard
    Anthropic model; the Supervisor overrides this to route "simple"
    categorization requests to Groq/Llama instead), then compares the
    transaction's amount (in Python, not by the LLM) against the user's
    average weekly spend in that category - falling back to the average
    of recent same-category transactions if there's no distinct prior
    week of history yet - and flags it as an anomaly if it's more than
    2.5x that baseline. Updates the transaction's category_id directly
    and, if flagged, writes an Anomaly row with the reason.
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

        predicted_category = await _predict_category(transaction.merchant, transaction.amount, model=model)

        category_result = await session.execute(
            select(Category).where(Category.name == predicted_category)
        )
        category = category_result.scalar_one_or_none()
        if category is None:
            category = Category(name=predicted_category)
            session.add(category)
            await session.flush()

        average, baseline_description = await _get_anomaly_baseline(
            owner_id, category.id, transaction.date, transaction.id
        )

        is_anomaly = False
        reason = None
        if average is not None and average > 0 and transaction.amount > ANOMALY_MULTIPLIER * average:
            is_anomaly = True
            reason = (
                f"Amount Rs. {transaction.amount:.2f} is "
                f"{transaction.amount / average:.1f}x the {baseline_description}."
            )

        transaction.category_id = category.id
        transaction.is_anomaly = is_anomaly
        transaction.categorized_by_model = model

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
            "model_used": model,
        }

    await save_trace(
        owner_id,
        f"Categorize transaction {transaction_id}",
        "categorization",
        [{"agent": "categorization_agent", "action": "categorize_transaction", "result": result}],
    )

    return result
