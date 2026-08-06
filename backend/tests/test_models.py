import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import Anomaly, Budget, Category, Transaction, TransactionSource, User


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_user(db_session) -> User:
    user = User(
        username=_unique("user"),
        email=f"{_unique('user')}@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_category(db_session, name: str | None = None) -> Category:
    category = Category(name=name or _unique("category"))
    db_session.add(category)
    await db_session.commit()
    await db_session.refresh(category)
    return category


async def test_transaction_requires_owner_id(db_session):
    transaction = Transaction(merchant="Test Store", amount=10.0, source=TransactionSource.manual)
    db_session.add(transaction)
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_budget_requires_owner_id_and_category_id(db_session):
    budget = Budget(monthly_limit=100.0)
    db_session.add(budget)
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_category_name_must_be_unique(db_session):
    name = _unique("dup_category")
    db_session.add(Category(name=name))
    await db_session.commit()

    db_session.add(Category(name=name))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_anomaly_transaction_id_must_be_unique(db_session):
    user = await _make_user(db_session)
    category = await _make_category(db_session)

    transaction = Transaction(
        owner_id=user.id,
        merchant="Costco",
        amount=250.0,
        source=TransactionSource.manual,
        category_id=category.id,
    )
    db_session.add(transaction)
    await db_session.commit()
    await db_session.refresh(transaction)

    db_session.add(Anomaly(transaction_id=transaction.id, owner_id=user.id, reason="first flag"))
    await db_session.commit()

    # a second Anomaly row pointing at the same transaction should violate
    # the unique constraint - a transaction can only be flagged once.
    db_session.add(Anomaly(transaction_id=transaction.id, owner_id=user.id, reason="second flag"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_deleting_transaction_cascades_to_its_anomaly(db_session):
    user = await _make_user(db_session)
    category = await _make_category(db_session)

    transaction = Transaction(
        owner_id=user.id,
        merchant="Costco",
        amount=250.0,
        source=TransactionSource.manual,
        category_id=category.id,
    )
    db_session.add(transaction)
    await db_session.commit()
    await db_session.refresh(transaction)

    anomaly = Anomaly(transaction_id=transaction.id, owner_id=user.id, reason="too much")
    db_session.add(anomaly)
    await db_session.commit()
    anomaly_id = anomaly.id

    # reload with the anomaly relationship populated so the ORM cascade
    # (cascade="all, delete-orphan" on Transaction.anomaly) has something
    # loaded to cascade against.
    loaded = (
        await db_session.execute(
            select(Transaction)
            .options(selectinload(Transaction.anomaly))
            .where(Transaction.id == transaction.id)
        )
    ).scalar_one()
    await db_session.delete(loaded)
    await db_session.commit()

    remaining = await db_session.execute(select(Anomaly).where(Anomaly.id == anomaly_id))
    assert remaining.scalar_one_or_none() is None


async def test_deleting_user_cascades_to_transactions_budgets_and_anomalies(db_session):
    user = await _make_user(db_session)
    category = await _make_category(db_session)

    transaction = Transaction(
        owner_id=user.id,
        merchant="Costco",
        amount=250.0,
        source=TransactionSource.manual,
        category_id=category.id,
    )
    budget = Budget(owner_id=user.id, category_id=category.id, monthly_limit=100.0)
    db_session.add_all([transaction, budget])
    await db_session.commit()
    await db_session.refresh(transaction)

    anomaly = Anomaly(transaction_id=transaction.id, owner_id=user.id, reason="too much")
    db_session.add(anomaly)
    await db_session.commit()

    transaction_id, budget_id, anomaly_id, user_id = transaction.id, budget.id, anomaly.id, user.id

    loaded_user = (
        await db_session.execute(
            select(User)
            .options(
                selectinload(User.transactions).selectinload(Transaction.anomaly),
                selectinload(User.budgets),
                selectinload(User.anomalies),
            )
            .where(User.id == user_id)
        )
    ).scalar_one()
    await db_session.delete(loaded_user)
    await db_session.commit()

    assert (await db_session.execute(select(User).where(User.id == user_id))).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Transaction).where(Transaction.id == transaction_id))
    ).scalar_one_or_none() is None
    assert (await db_session.execute(select(Budget).where(Budget.id == budget_id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(Anomaly).where(Anomaly.id == anomaly_id))).scalar_one_or_none() is None
