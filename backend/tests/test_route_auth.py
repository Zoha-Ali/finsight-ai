import io

import pytest

# (method, path, kwargs) for every route that depends on get_current_user.
# Bodies/files are filled in with well-formed placeholder data so a
# request fails on auth (401), not on request validation (422) - that
# keeps this test purely about the auth dependency, not payload shape.
PROTECTED_ENDPOINTS = [
    ("GET", "/transactions", {}),
    ("POST", "/transactions", {"json": {"merchant": "Test", "amount": 10.0, "date": "2026-01-01"}}),
    ("DELETE", "/transactions/1", {}),
    ("POST", "/receipts/upload", {"files": {"file": ("r.png", io.BytesIO(b"x"), "image/png")}}),
    ("POST", "/categorize", {"json": {"transaction_id": 1}}),
    ("GET", "/forecast", {}),
    ("POST", "/qa", {"json": {"question": "How much did I spend?"}}),
    ("GET", "/categories", {}),
    ("GET", "/budgets", {}),
    ("POST", "/budgets", {"json": {"category_id": 1, "monthly_limit": 100.0}}),
    ("DELETE", "/budgets/1", {}),
    ("GET", "/anomalies", {}),
    ("GET", "/traces", {}),
]


@pytest.mark.parametrize(
    "method, path, kwargs", PROTECTED_ENDPOINTS, ids=[f"{m} {p}" for m, p, _ in PROTECTED_ENDPOINTS]
)
async def test_protected_route_rejects_request_without_a_token(client, method, path, kwargs):
    response = await client.request(method, path, **kwargs)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method, path, kwargs", PROTECTED_ENDPOINTS, ids=[f"{m} {p}" for m, p, _ in PROTECTED_ENDPOINTS]
)
async def test_protected_route_rejects_a_garbage_token(client, method, path, kwargs):
    headers = {"Authorization": "Bearer not-a-real-token"}
    response = await client.request(method, path, headers=headers, **kwargs)
    assert response.status_code == 401


async def test_signup_does_not_require_a_token(client, db_session):
    response = await client.post(
        "/auth/signup",
        json={"username": "route_auth_signup_test", "email": "route_auth_signup_test@example.com", "password": "x"},
    )
    assert response.status_code == 201


async def test_login_does_not_require_a_token(client, test_user):
    response = await client.post(
        "/auth/login",
        data={"username": test_user.username, "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
