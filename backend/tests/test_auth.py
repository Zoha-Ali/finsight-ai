from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.auth import (
    _create_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)


def test_verify_password_accepts_the_original_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_verify_password_rejects_a_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_hash_password_produces_a_different_hash_each_time():
    # bcrypt salts every hash independently, so hashing the same password
    # twice must not produce identical output (rules out a broken/no-op salt).
    first = hash_password("same password")
    second = hash_password("same password")
    assert first != second
    assert verify_password("same password", first)
    assert verify_password("same password", second)


def test_hash_password_handles_passwords_longer_than_bcrypts_72_byte_limit():
    # bcrypt silently truncates raw input at 72 bytes; the SHA-256 pre-hash
    # in hash_password exists specifically to avoid that truncation
    # silently treating two different long passwords as equal.
    long_a = "a" * 100
    long_b = "a" * 99 + "b"
    hashed_a = hash_password(long_a)
    assert verify_password(long_a, hashed_a)
    assert not verify_password(long_b, hashed_a)


def test_create_access_token_has_type_access_and_correct_expiry():
    token = create_access_token(user_id=42, token_version=0)
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["type"] == "access"
    assert payload["token_version"] == 0
    assert payload["exp"] - payload["iat"] == timedelta(days=2).total_seconds()


def test_create_refresh_token_has_type_refresh_and_correct_expiry():
    token = create_refresh_token(user_id=42, token_version=0)
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["type"] == "refresh"
    assert payload["token_version"] == 0
    assert payload["exp"] - payload["iat"] == timedelta(days=5).total_seconds()


def test_decode_token_rejects_a_garbage_token():
    with pytest.raises(HTTPException) as exc_info:
        decode_token("not.a.valid.jwt")
    assert exc_info.value.status_code == 401


def test_decode_token_rejects_an_expired_token():
    expired_token = _create_token(
        user_id=1, token_type="access", token_version=0, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_token(expired_token)
    assert exc_info.value.status_code == 401


async def test_get_current_user_rejects_a_refresh_token_used_as_bearer(db_session, test_user):
    refresh_token = create_refresh_token(test_user.id, test_user.token_version)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=refresh_token, db=db_session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_accepts_a_valid_access_token(db_session, test_user):
    access_token = create_access_token(test_user.id, test_user.token_version)
    user = await get_current_user(token=access_token, db=db_session)
    assert user.id == test_user.id


async def test_get_current_user_rejects_a_token_for_a_nonexistent_user(db_session):
    token_for_missing_user = create_access_token(user_id=999_999_999, token_version=0)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token_for_missing_user, db=db_session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_rejects_a_token_with_a_stale_token_version(db_session, test_user):
    # Simulates a token issued before a logout bumped token_version - the
    # exact mechanism logout relies on to invalidate outstanding tokens.
    stale_token = create_access_token(test_user.id, test_user.token_version)
    test_user.token_version += 1
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=stale_token, db=db_session)
    assert exc_info.value.status_code == 401
