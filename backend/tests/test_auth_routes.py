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
    refresh_token = create_refresh_token(test_user.id, test_user.token_version)
    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_refresh_rejects_an_access_token_used_as_a_refresh_token(client, test_user):
    access_token = create_access_token(test_user.id, test_user.token_version)
    response = await client.post("/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


async def test_refresh_rejects_a_token_for_a_deleted_user(client):
    token_for_missing_user = create_refresh_token(user_id=999_999_999, token_version=0)
    response = await client.post("/auth/refresh", json={"refresh_token": token_for_missing_user})
    assert response.status_code == 401


async def test_logout_returns_204_and_bumps_token_version(client, db_session, test_user, auth_headers):
    starting_version = test_user.token_version

    response = await client.post("/auth/logout", headers=auth_headers)

    assert response.status_code == 204
    await db_session.refresh(test_user)
    assert test_user.token_version == starting_version + 1


async def test_logout_invalidates_a_previously_valid_access_token(client, test_user, auth_headers):
    # Sanity check: the token works before logout.
    assert (await client.get("/transactions", headers=auth_headers)).status_code == 200

    logout_response = await client.post("/auth/logout", headers=auth_headers)
    assert logout_response.status_code == 204

    # The exact same access token, now stale, must be rejected.
    response = await client.get("/transactions", headers=auth_headers)
    assert response.status_code == 401


async def test_logout_invalidates_a_previously_valid_refresh_token(client, test_user, auth_headers):
    refresh_token = create_refresh_token(test_user.id, test_user.token_version)
    # Sanity check: the refresh token works before logout.
    assert (await client.post("/auth/refresh", json={"refresh_token": refresh_token})).status_code == 200

    logout_response = await client.post("/auth/logout", headers=auth_headers)
    assert logout_response.status_code == 204

    # The exact same refresh token, now stale, must no longer mint a new access token.
    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401


async def test_login_after_logout_issues_working_tokens(client, test_user, auth_headers):
    logout_response = await client.post("/auth/logout", headers=auth_headers)
    assert logout_response.status_code == 204

    login_response = await client.post(
        "/auth/login",
        data={"username": test_user.username, "password": "correct horse battery staple"},
    )
    assert login_response.status_code == 200
    new_tokens = login_response.json()

    # The fresh access token works normally against a protected route...
    new_headers = {"Authorization": f"Bearer {new_tokens['access_token']}"}
    assert (await client.get("/transactions", headers=new_headers)).status_code == 200

    # ...and the fresh refresh token works normally too.
    refresh_response = await client.post("/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert refresh_response.status_code == 200
