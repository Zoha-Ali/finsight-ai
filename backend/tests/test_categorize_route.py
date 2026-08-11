from unittest.mock import AsyncMock

from app.routes import categorize as categorize_route


async def test_categorize_route_returns_the_agent_result(monkeypatch, client, auth_headers):
    monkeypatch.setattr(
        categorize_route,
        "categorize_transaction",
        AsyncMock(
            return_value={
                "transaction_id": 1,
                "category": "food",
                "category_id": 2,
                "is_anomaly": False,
                "reason": None,
            }
        ),
    )

    response = await client.post("/categorize", json={"transaction_id": 1}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["category"] == "food"


async def test_categorize_route_maps_value_error_to_404(monkeypatch, client, auth_headers):
    monkeypatch.setattr(
        categorize_route,
        "categorize_transaction",
        AsyncMock(side_effect=ValueError("Transaction 999 not found for owner 1")),
    )

    response = await client.post("/categorize", json={"transaction_id": 999}, headers=auth_headers)

    assert response.status_code == 404
