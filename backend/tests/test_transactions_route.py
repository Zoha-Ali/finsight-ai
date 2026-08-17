import uuid
from unittest.mock import AsyncMock

from app.models import Category
from app.routes import transactions as transactions_route


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def test_create_transaction_categorizes_it_and_returns_the_result(monkeypatch, client, auth_headers):
    # categorize_transaction makes a real LLM call and its own DB writes -
    # not the point of this route test, so it's mocked; the route's own
    # job (create the row, call categorize, return the enriched result)
    # is what's under test here.
    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    response = await client.post(
        "/transactions",
        json={"merchant": "Trader Joe's", "amount": 42.0, "date": "2026-03-05"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["merchant"] == "Trader Joe's"
    assert body["amount"] == 42.0
    assert body["source"] == "manual"
    transactions_route.categorize_transaction.assert_awaited_once()


async def test_create_transaction_returns_the_category_name_when_categorized(
    monkeypatch, client, db_session, auth_headers
):
    category = Category(name=_unique("food"))
    db_session.add(category)
    await db_session.commit()
    await db_session.refresh(category)

    async def fake_categorize(transaction_id, owner_id):
        # Simulate what the real agent does: set category_id on the row.
        # Opens its own short-lived session (via the same patched
        # AsyncSessionLocal the app itself uses per call) instead of
        # reusing the long-lived db_session fixture - interleaving writes
        # from two sessions that are both still open on the same
        # SAVEPOINT-nested test connection confuses SQLAlchemy's
        # savepoint bookkeeping (raises InvalidSavepointSpecificationError).
        from sqlalchemy import select

        from app import database
        from app.models import Transaction

        async with database.AsyncSessionLocal() as session:
            transaction = (
                await session.execute(select(Transaction).where(Transaction.id == transaction_id))
            ).scalar_one()
            transaction.category_id = category.id
            await session.commit()

    monkeypatch.setattr(transactions_route, "categorize_transaction", fake_categorize)

    response = await client.post(
        "/transactions",
        json={"merchant": "Whole Foods", "amount": 30.0, "date": "2026-03-05"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["category_name"] == category.name


async def test_list_transactions_returns_only_the_current_users_transactions(
    monkeypatch, client, db_session, auth_headers, test_user
):
    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    await client.post(
        "/transactions", json={"merchant": "Store A", "amount": 10.0, "date": "2026-03-01"}, headers=auth_headers
    )

    response = await client.get("/transactions", headers=auth_headers)

    assert response.status_code == 200
    merchants = [t["merchant"] for t in response.json()]
    assert "Store A" in merchants


async def test_delete_transaction_removes_it(monkeypatch, client, auth_headers):
    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    create_response = await client.post(
        "/transactions", json={"merchant": "Delete Me", "amount": 5.0, "date": "2026-03-01"}, headers=auth_headers
    )
    transaction_id = create_response.json()["id"]

    delete_response = await client.delete(f"/transactions/{transaction_id}", headers=auth_headers)
    assert delete_response.status_code == 204

    list_response = await client.get("/transactions", headers=auth_headers)
    assert transaction_id not in [t["id"] for t in list_response.json()]


async def test_delete_transaction_returns_404_for_a_nonexistent_transaction(client, auth_headers):
    response = await client.delete("/transactions/999999999", headers=auth_headers)
    assert response.status_code == 404


async def test_delete_transaction_returns_403_for_another_users_transaction(
    monkeypatch, client, db_session, auth_headers
):
    from app.auth import create_access_token, hash_password
    from app.models import User

    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    other_user = User(
        username=_unique("other_user"),
        email=f"{_unique('other_user')}@example.com",
        hashed_password=hash_password("x"),
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)
    other_headers = {"Authorization": f"Bearer {create_access_token(other_user.id)}"}

    create_response = await client.post(
        "/transactions",
        json={"merchant": "Owned By Other", "amount": 5.0, "date": "2026-03-01"},
        headers=other_headers,
    )
    transaction_id = create_response.json()["id"]

    response = await client.delete(f"/transactions/{transaction_id}", headers=auth_headers)
    assert response.status_code == 403


async def _create_flagged_anomaly(client, db_session, auth_headers, test_user, monkeypatch):
    """Creates a transaction and flags it as an anomaly directly in the DB
    (bypassing the real categorization LLM call, same as the other tests
    in this file), returning its id.
    """
    from app.models import Anomaly

    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    create_response = await client.post(
        "/transactions",
        json={"merchant": "Suspiciously Large Purchase", "amount": 999.0, "date": "2026-03-01"},
        headers=auth_headers,
    )
    transaction_id = create_response.json()["id"]

    from sqlalchemy import select

    from app.models import Transaction

    transaction = (
        await db_session.execute(select(Transaction).where(Transaction.id == transaction_id))
    ).scalar_one()
    transaction.is_anomaly = True
    db_session.add(Anomaly(owner_id=test_user.id, transaction_id=transaction_id, reason="Way above average."))
    await db_session.commit()

    return transaction_id


async def test_approve_transaction_clears_the_anomaly_flag_and_deletes_the_anomaly_row(
    monkeypatch, client, db_session, auth_headers, test_user
):
    from sqlalchemy import select

    from app.models import Anomaly

    transaction_id = await _create_flagged_anomaly(client, db_session, auth_headers, test_user, monkeypatch)

    response = await client.patch(f"/transactions/{transaction_id}/approve", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["is_anomaly"] is False

    remaining_anomaly = (
        await db_session.execute(select(Anomaly).where(Anomaly.transaction_id == transaction_id))
    ).scalar_one_or_none()
    assert remaining_anomaly is None

    list_response = await client.get("/transactions", headers=auth_headers)
    listed = next(t for t in list_response.json() if t["id"] == transaction_id)
    assert listed["is_anomaly"] is False


async def test_approve_transaction_returns_404_for_a_nonexistent_transaction(client, auth_headers):
    response = await client.patch("/transactions/999999999/approve", headers=auth_headers)
    assert response.status_code == 404


async def test_approve_transaction_returns_404_for_another_users_transaction(
    monkeypatch, client, db_session, auth_headers, test_user
):
    from app.auth import create_access_token, hash_password
    from app.models import User

    other_user = User(
        username=_unique("other_user"),
        email=f"{_unique('other_user')}@example.com",
        hashed_password=hash_password("x"),
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)
    other_headers = {"Authorization": f"Bearer {create_access_token(other_user.id)}"}

    transaction_id = await _create_flagged_anomaly(client, db_session, other_headers, other_user, monkeypatch)

    # A transaction that exists but belongs to someone else 404s exactly
    # like a nonexistent one - it must not leak whether the id exists via
    # a 403 instead.
    response = await client.patch(f"/transactions/{transaction_id}/approve", headers=auth_headers)
    assert response.status_code == 404


async def test_create_transaction_rejects_a_future_date(monkeypatch, client, auth_headers):
    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    import datetime

    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    response = await client.post(
        "/transactions",
        json={"merchant": "Time Traveler Purchase", "amount": 10.0, "date": tomorrow},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "cannot be in the future" in response.json()["detail"]

    # rejected before any DB write happened
    list_response = await client.get("/transactions", headers=auth_headers)
    merchants = [t["merchant"] for t in list_response.json()]
    assert "Time Traveler Purchase" not in merchants


async def test_create_transaction_accepts_todays_date(monkeypatch, client, auth_headers):
    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    import datetime

    today = datetime.date.today().isoformat()

    response = await client.post(
        "/transactions",
        json={"merchant": "Same Day Purchase", "amount": 10.0, "date": today},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["date"] == today


async def test_create_transaction_accepts_a_past_date(monkeypatch, client, auth_headers):
    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    response = await client.post(
        "/transactions",
        json={"merchant": "Old Purchase", "amount": 10.0, "date": "2020-01-01"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["date"] == "2020-01-01"


async def test_approve_transaction_returns_400_when_not_flagged_as_anomaly(monkeypatch, client, auth_headers):
    monkeypatch.setattr(transactions_route, "categorize_transaction", AsyncMock(return_value=None))

    create_response = await client.post(
        "/transactions",
        json={"merchant": "Ordinary Purchase", "amount": 5.0, "date": "2026-03-01"},
        headers=auth_headers,
    )
    transaction_id = create_response.json()["id"]

    response = await client.patch(f"/transactions/{transaction_id}/approve", headers=auth_headers)
    assert response.status_code == 400
