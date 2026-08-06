import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents import categorization_agent
from app.models import Anomaly, Category, Transaction, TransactionSource


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# --- Part 1: _get_anomaly_baseline in isolation (no DB, no LLM) ------------


async def test_baseline_prefers_weekly_average_when_available(monkeypatch):
    monkeypatch.setattr(
        categorization_agent,
        "get_weekly_average",
        AsyncMock(return_value={"average_weekly_spend": 30.0, "weeks_counted": 3}),
    )
    get_transactions_mock = AsyncMock()
    monkeypatch.setattr(categorization_agent, "get_transactions", get_transactions_mock)

    average, description = await categorization_agent._get_anomaly_baseline(
        owner_id=1, category_id=1, transaction_date=date(2026, 3, 5), exclude_transaction_id=99
    )

    assert average == 30.0
    assert "week" in description.lower()
    get_transactions_mock.assert_not_awaited()  # weekly average was enough, no need for the fallback


async def test_baseline_falls_back_to_recent_transactions_when_no_prior_week(monkeypatch):
    monkeypatch.setattr(categorization_agent, "get_weekly_average", AsyncMock(return_value=None))
    monkeypatch.setattr(
        categorization_agent,
        "get_transactions",
        AsyncMock(
            return_value=[
                {"id": 1, "amount": 10.0, "category_id": 5},
                {"id": 2, "amount": 20.0, "category_id": 5},
                {"id": 3, "amount": 999.0, "category_id": 7},  # different category - must be excluded
            ]
        ),
    )

    average, description = await categorization_agent._get_anomaly_baseline(
        owner_id=1, category_id=5, transaction_date=date(2026, 3, 5), exclude_transaction_id=99
    )

    assert average == 15.0  # (10 + 20) / 2, category 7's amount excluded
    assert "average of the user's last" in description


async def test_baseline_fallback_excludes_the_transaction_being_evaluated(monkeypatch):
    monkeypatch.setattr(categorization_agent, "get_weekly_average", AsyncMock(return_value=None))
    monkeypatch.setattr(
        categorization_agent,
        "get_transactions",
        AsyncMock(
            return_value=[
                {"id": 1, "amount": 10.0, "category_id": 5},
                {"id": 2, "amount": 20.0, "category_id": 5},
            ]
        ),
    )

    average, _ = await categorization_agent._get_anomaly_baseline(
        owner_id=1, category_id=5, transaction_date=date(2026, 3, 5), exclude_transaction_id=1
    )

    assert average == 20.0  # transaction id=1 excluded, only the $20 one counts


async def test_baseline_treats_a_zero_weekly_average_as_no_baseline_and_falls_back(monkeypatch):
    # average_weekly_spend=0 should not be used directly (0 as a threshold
    # would flag literally any positive spend as an anomaly) - the code
    # checks `> 0` before trusting it, so this must fall through instead.
    monkeypatch.setattr(
        categorization_agent,
        "get_weekly_average",
        AsyncMock(return_value={"average_weekly_spend": 0.0, "weeks_counted": 1}),
    )
    monkeypatch.setattr(
        categorization_agent,
        "get_transactions",
        AsyncMock(return_value=[{"id": 1, "amount": 40.0, "category_id": 5}]),
    )

    average, description = await categorization_agent._get_anomaly_baseline(
        owner_id=1, category_id=5, transaction_date=date(2026, 3, 5), exclude_transaction_id=99
    )

    assert average == 40.0
    assert "average of the user's last" in description


async def test_baseline_returns_none_with_no_data_of_any_kind(monkeypatch):
    monkeypatch.setattr(categorization_agent, "get_weekly_average", AsyncMock(return_value=None))
    monkeypatch.setattr(categorization_agent, "get_transactions", AsyncMock(return_value=[]))

    average, description = await categorization_agent._get_anomaly_baseline(
        owner_id=1, category_id=5, transaction_date=date(2026, 3, 5), exclude_transaction_id=99
    )

    assert average is None
    assert description == ""


# --- Part 2: categorize_transaction's 2.5x threshold, end to end ----------
# Real DB (transactional test session) + real weekly-average math, only
# the LLM category-prediction call is mocked.


async def _seed_transaction(db_session, owner_id: int, category_id: int, amount: float, tx_date: date) -> int:
    transaction = Transaction(
        owner_id=owner_id,
        merchant="Test Merchant",
        amount=amount,
        date=tx_date,
        source=TransactionSource.manual,
        category_id=category_id,
    )
    db_session.add(transaction)
    await db_session.commit()
    await db_session.refresh(transaction)
    return transaction.id


async def test_categorize_transaction_flags_amount_over_2_5x_weekly_average(monkeypatch, db_session, test_user):
    category = Category(name=_unique("shopping"))
    db_session.add(category)
    await db_session.commit()
    await db_session.refresh(category)

    monkeypatch.setattr(categorization_agent, "_predict_category", AsyncMock(return_value=category.name))

    today = date.today()
    # 3 prior weeks averaging $20/week
    for weeks_back in (1, 2, 3):
        await _seed_transaction(db_session, test_user.id, category.id, 20.0, today - timedelta(weeks=weeks_back))

    new_transaction_id = await _seed_transaction(db_session, test_user.id, category.id, 100.0, today)
    # amount=100 is not yet categorized (category_id above is only used
    # for seeding history under the same category by name lookup below);
    # clear it so categorize_transaction has to predict it itself.
    new_transaction = (
        await db_session.execute(select(Transaction).where(Transaction.id == new_transaction_id))
    ).scalar_one()
    new_transaction.category_id = None
    await db_session.commit()

    result = await categorization_agent.categorize_transaction(new_transaction_id, test_user.id)

    assert result["category"] == category.name
    assert result["is_anomaly"] is True
    assert "5.0x" in result["reason"]  # 100 / 20 = 5.0

    anomaly = (
        await db_session.execute(select(Anomaly).where(Anomaly.transaction_id == new_transaction_id))
    ).scalar_one_or_none()
    assert anomaly is not None
    assert anomaly.reason == result["reason"]


async def test_categorize_transaction_does_not_flag_amount_under_2_5x_weekly_average(
    monkeypatch, db_session, test_user
):
    category = Category(name=_unique("food"))
    db_session.add(category)
    await db_session.commit()
    await db_session.refresh(category)

    monkeypatch.setattr(categorization_agent, "_predict_category", AsyncMock(return_value=category.name))

    today = date.today()
    await _seed_transaction(db_session, test_user.id, category.id, 20.0, today - timedelta(weeks=1))

    # $40 is exactly 2x the $20/week average - below the 2.5x threshold.
    new_transaction_id = await _seed_transaction(db_session, test_user.id, category.id, 40.0, today)
    new_transaction = (
        await db_session.execute(select(Transaction).where(Transaction.id == new_transaction_id))
    ).scalar_one()
    new_transaction.category_id = None
    await db_session.commit()

    result = await categorization_agent.categorize_transaction(new_transaction_id, test_user.id)

    assert result["is_anomaly"] is False
    assert result["reason"] is None

    anomaly = (
        await db_session.execute(select(Anomaly).where(Anomaly.transaction_id == new_transaction_id))
    ).scalar_one_or_none()
    assert anomaly is None


async def test_categorize_transaction_updates_existing_anomaly_instead_of_duplicating(
    monkeypatch, db_session, test_user
):
    category = Category(name=_unique("entertainment"))
    db_session.add(category)
    await db_session.commit()
    await db_session.refresh(category)

    monkeypatch.setattr(categorization_agent, "_predict_category", AsyncMock(return_value=category.name))

    today = date.today()
    await _seed_transaction(db_session, test_user.id, category.id, 10.0, today - timedelta(weeks=1))

    transaction_id = await _seed_transaction(db_session, test_user.id, category.id, 100.0, today)
    transaction = (
        await db_session.execute(select(Transaction).where(Transaction.id == transaction_id))
    ).scalar_one()
    transaction.category_id = None
    await db_session.commit()

    first_result = await categorization_agent.categorize_transaction(transaction_id, test_user.id)
    assert first_result["is_anomaly"] is True

    # re-running categorization on the same transaction (e.g. a retry)
    # should update the same Anomaly row, not create a second one.
    second_result = await categorization_agent.categorize_transaction(transaction_id, test_user.id)
    assert second_result["is_anomaly"] is True

    anomalies = (
        await db_session.execute(select(Anomaly).where(Anomaly.transaction_id == transaction_id))
    ).scalars().all()
    assert len(anomalies) == 1
