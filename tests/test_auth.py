"""Telegram hash verify, JWT round-trip, allowlist."""
import hashlib
import hmac
import time

import pytest

from src import auth, config


def _sign(data: dict, token: str) -> str:
    """Build a valid Telegram Login Widget hash for `data` using `token`."""
    items = sorted(f"{k}={v}" for k, v in data.items() if k != "hash")
    data_check_string = "\n".join(items)
    secret_key = hashlib.sha256(token.encode()).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def _make_payload(user_id: int = 5904148250, age_seconds: int = 0) -> dict:
    config.BOT_TOKEN = "test-bot-token"  # ensure fresh signing key
    payload = {
        "id": user_id,
        "first_name": "Abdullah",
        "auth_date": int(time.time()) - age_seconds,
    }
    payload["hash"] = _sign(payload, config.BOT_TOKEN)
    return payload


def test_verify_valid_hash():
    payload = _make_payload()
    assert auth.verify_telegram_hash(payload) is True


def test_verify_rejects_tampered_hash():
    payload = _make_payload()
    payload["hash"] = "0" * 64
    assert auth.verify_telegram_hash(payload) is False


def test_verify_rejects_stale_auth():
    payload = _make_payload(age_seconds=86400 + 100)  # > 24h old
    assert auth.verify_telegram_hash(payload) is False


def test_verify_rejects_missing_hash():
    payload = _make_payload()
    del payload["hash"]
    assert auth.verify_telegram_hash(payload) is False


def test_jwt_roundtrip():
    config.SECRET_KEY = "test-secret-key-32-characters-long"
    token = auth.create_session_token(5904148250)
    user_id = auth.decode_session_token(token)
    assert user_id == 5904148250


def test_jwt_rejects_bad_token():
    config.SECRET_KEY = "test-secret-key-32-characters-long"
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        auth.decode_session_token("not.a.real.token")


@pytest.mark.asyncio
async def test_is_user_allowed_yes(seeded_bot_db):
    assert await auth.is_user_allowed(5904148250) is True


@pytest.mark.asyncio
async def test_is_user_allowed_no(seeded_bot_db):
    # 999 is in neither the env allowlist nor the bot's allowed_users table
    assert await auth.is_user_allowed(999) is False


@pytest.mark.asyncio
async def test_env_allowlist_blocks_unknown_user(seeded_bot_db, monkeypatch):
    """Even if user is in the bot's table, the env allowlist gate must match."""
    monkeypatch.setattr(config, "ALLOWED_USERS", {1234})  # narrower env allowlist
    assert await auth.is_user_allowed(5904148250) is False
