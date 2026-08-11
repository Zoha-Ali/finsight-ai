from unittest.mock import AsyncMock

from app.routes import qa as qa_route


async def test_qa_route_returns_the_agent_result(monkeypatch, client, auth_headers):
    monkeypatch.setattr(
        qa_route,
        "route_request",
        AsyncMock(
            return_value={
                "agent_used": "qa",
                "result": {"answer": "You spent $42 this month."},
                "trace": [{"agent": "qa_agent"}],
                "table": None,
            }
        ),
    )

    response = await client.post("/qa", json={"question": "How much did I spend?"}, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["agent_used"] == "qa"
    assert body["result"]["answer"] == "You spent $42 this month."


async def test_qa_route_maps_value_error_to_404(monkeypatch, client, auth_headers):
    monkeypatch.setattr(qa_route, "route_request", AsyncMock(side_effect=ValueError("nothing to route to")))

    response = await client.post("/qa", json={"question": "???"}, headers=auth_headers)

    assert response.status_code == 404
