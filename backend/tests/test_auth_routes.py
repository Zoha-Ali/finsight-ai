from app.auth import create_access_token, create_refresh_token


async def test_signup_rejects_a_duplicate_username_or_email(client, test_user):
    response = await client.post(
        "/auth/signup",
        json={"username": test_user.username, "email": "someone_else@example.com", "password": "x"},
    )
    assert response.status_code == 409


async def test_login_rejects_a_wrong_password(client, test_user):
    response = await client.post(
        "/auth/login", data={"username": test_user.username, "password": "wrong password"}
    )
    assert response.status_code == 401


async def test_login_rejects_an_unknown_username(client):
    response = await client.post(
        "/auth/login", data={"username": "no_such_user", "password": "whatever"}
    )
    assert response.status_code == 401


async def test_refresh_issues_a_new_access_token_for_a_valid_refresh_token(client, test_user):
    refresh_token = create_refresh_token(test_user.id)
    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_refresh_rejects_an_access_token_used_as_a_refresh_token(client, test_user):
    access_token = create_access_token(test_user.id)
    response = await client.post("/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


async def test_refresh_rejects_a_token_for_a_deleted_user(client):
    token_for_missing_user = create_refresh_token(user_id=999_999_999)
    response = await client.post("/auth/refresh", json={"refresh_token": token_for_missing_user})
    assert response.status_code == 401
