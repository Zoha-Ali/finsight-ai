import uuid

from sqlalchemy import select

from app.models import Budget, Category


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_category(db_session) -> Category:
    category = Category(name=_unique("budget_test_category"))
    db_session.add(category)
    await db_session.commit()
    await db_session.refresh(category)
    return category


async def test_posting_a_budget_twice_for_the_same_category_updates_not_duplicates(
    client, db_session, auth_headers, test_user
):
    category = await _make_category(db_session)

    first = await client.post(
        "/budgets", json={"category_id": category.id, "monthly_limit": 100.0}, headers=auth_headers
    )
    assert first.status_code == 200
    assert first.json()["monthly_limit"] == 100.0
    first_budget_id = first.json()["id"]

    second = await client.post(
        "/budgets", json={"category_id": category.id, "monthly_limit": 250.0}, headers=auth_headers
    )
    assert second.status_code == 200
    assert second.json()["monthly_limit"] == 250.0
    assert second.json()["id"] == first_budget_id  # same row, not a new one

    rows = (
        await db_session.execute(
            select(Budget).where(Budget.owner_id == test_user.id, Budget.category_id == category.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].monthly_limit == 250.0


async def test_budgets_for_different_categories_do_not_collide(client, db_session, auth_headers, test_user):
    category_a = await _make_category(db_session)
    category_b = await _make_category(db_session)

    await client.post("/budgets", json={"category_id": category_a.id, "monthly_limit": 100.0}, headers=auth_headers)
    await client.post("/budgets", json={"category_id": category_b.id, "monthly_limit": 200.0}, headers=auth_headers)

    rows = (await db_session.execute(select(Budget).where(Budget.owner_id == test_user.id))).scalars().all()
    assert len(rows) == 2


async def test_posting_a_budget_for_a_nonexistent_category_returns_404(client, auth_headers):
    response = await client.post("/budgets", json={"category_id": 999_999_999, "monthly_limit": 50.0}, headers=auth_headers)
    assert response.status_code == 404


async def test_deleting_a_budget_removes_it(client, db_session, auth_headers, test_user):
    category = await _make_category(db_session)
    await client.post("/budgets", json={"category_id": category.id, "monthly_limit": 100.0}, headers=auth_headers)

    response = await client.delete(f"/budgets/{category.id}", headers=auth_headers)
    assert response.status_code == 204

    rows = (
        await db_session.execute(
            select(Budget).where(Budget.owner_id == test_user.id, Budget.category_id == category.id)
        )
    ).scalars().all()
    assert rows == []


async def test_deleting_a_budget_that_does_not_exist_returns_404(client, auth_headers):
    response = await client.delete("/budgets/999999999", headers=auth_headers)
    assert response.status_code == 404
