"""Telegram Login Widget verification + JWT session cookies.

Spec: https://core.telegram.org/widgets/login#checking-authorization
Pattern copied from prayer-web with one bug-fix (corrected db_uri import).
"""
import hashlib
import hmac
import time

import aiosqlite
from fastapi import Cookie, HTTPException
from jose import JWTError, jwt

from src import config
from src.db import db_uri

ALGORITHM = "HS256"
SESSION_DAYS = 30


def verify_telegram_hash(data: dict) -> bool:
    """Verify the hash sent by the Telegram Login Widget."""
    received_hash = data.get("hash", "")
    check_data = {k: v for k, v in data.items() if k != "hash"}
    data_check_string = "\n".join(
        sorted(f"{k}={v}" for k, v in check_data.items())
    )
    secret_key = hashlib.sha256(config.BOT_TOKEN.encode()).digest()
    expected = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if expected != received_hash:
        return False
    # Reject auth data older than 24 hours
    auth_date = int(data.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        return False
    return True


def create_session_token(user_id: int) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    return jwt.encode(
        {"user_id": user_id, "exp": exp},
        config.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_session_token(token: str) -> int:
    """Returns user_id, raises HTTPException(401) on invalid/expired token."""
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid session")
        return int(user_id)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid session")


async def is_user_allowed(user_id: int) -> bool:
    """Check the bot's allowed_users table.

    Empty whitelist → public access (we still gate via ALLOWED_USERS env).
    """
    # Belt-and-braces: also enforce the env-var allowlist.
    if config.ALLOWED_USERS and user_id not in config.ALLOWED_USERS:
        return False

    async with aiosqlite.connect(db_uri(), uri=True) as db:
        async with db.execute("SELECT COUNT(*) FROM allowed_users") as cur:
            total = (await cur.fetchone())[0]
        if total == 0:
            return True
        async with db.execute(
            "SELECT 1 FROM allowed_users WHERE user_id = ? LIMIT 1",
            (user_id,),
        ) as cur:
            return (await cur.fetchone()) is not None


def get_current_user(session: str | None = Cookie(default=None)) -> int:
    """FastAPI dependency — returns user_id from session cookie or 401s."""
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return decode_session_token(session)
