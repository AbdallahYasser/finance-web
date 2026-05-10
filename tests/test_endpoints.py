"""HTTP endpoint tests via httpx ASGI client. Auth + writes + rate-limit."""
import time

import pytest
from httpx import ASGITransport, AsyncClient


def _make_jwt(user_id: int) -> str:
    from src import auth, config
    config.SECRET_KEY = "test-secret-key-32-characters-long"
    return auth.create_session_token(user_id)


@pytest.mark.asyncio
async def test_unauth_post_blocked(w4_db, monkeypatch):
    from src import auth, config
    monkeypatch.setattr(config, "ALLOWED_USERS", {5904148250})
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key-32-characters-long")
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")

    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/transactions",
                          json={"type": "spend", "amount_cents": 100, "source_wallet_id": 1})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_post_create_transaction(w4_db, monkeypatch):
    from src import auth, config
    monkeypatch.setattr(config, "ALLOWED_USERS", {5904148250})
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key-32-characters-long")
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")
    # Reset rate-limiter so prior tests don't pollute
    from src import middleware
    middleware._BUCKETS.clear()

    from src.main import app
    token = _make_jwt(5904148250)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"session": token}) as ac:
        r = await ac.post("/api/transactions",
                          json={"type": "spend", "amount_cents": 250,
                                "source_wallet_id": 1, "category_id": 1,
                                "occurred_at": "2026-05-10T12:00:00Z"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["id"] > 0
        assert body["row"]["amount_cents"] == 250


@pytest.mark.asyncio
async def test_validation_400_on_bad_amount(w4_db, monkeypatch):
    from src import config, middleware
    monkeypatch.setattr(config, "ALLOWED_USERS", {5904148250})
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key-32-characters-long")
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")
    middleware._BUCKETS.clear()

    from src.main import app
    token = _make_jwt(5904148250)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"session": token}) as ac:
        r = await ac.post("/api/transactions",
                          json={"type": "spend", "amount_cents": 0, "source_wallet_id": 1})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_then_get_reflects_change(w4_db, monkeypatch):
    from src import config, middleware
    monkeypatch.setattr(config, "ALLOWED_USERS", {5904148250})
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key-32-characters-long")
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")
    middleware._BUCKETS.clear()

    from src.main import app
    token = _make_jwt(5904148250)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"session": token}) as ac:
        r = await ac.post("/api/transactions",
                          json={"type": "spend", "amount_cents": 100,
                                "source_wallet_id": 1, "category_id": 1,
                                "occurred_at": "2026-05-10T12:00:00Z"})
        tx_id = r.json()["id"]

        r = await ac.put(f"/api/transactions/{tx_id}",
                         json={"amount_cents": 250, "note": "updated"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["row"]["amount_cents"] == 250
        assert body["row"]["note"] == "updated"


@pytest.mark.asyncio
async def test_delete_and_restore_flow(w4_db, monkeypatch):
    from src import config, middleware
    monkeypatch.setattr(config, "ALLOWED_USERS", {5904148250})
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key-32-characters-long")
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")
    middleware._BUCKETS.clear()

    from src.main import app
    token = _make_jwt(5904148250)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"session": token}) as ac:
        r = await ac.post("/api/transactions",
                          json={"type": "spend", "amount_cents": 100,
                                "source_wallet_id": 1, "category_id": 1,
                                "occurred_at": "2026-05-10T12:00:00Z"})
        tx_id = r.json()["id"]

        r = await ac.delete(f"/api/transactions/{tx_id}")
        assert r.status_code == 204

        # tx now hidden by default search
        r = await ac.get("/api/transactions")
        ids = {row["id"] for row in r.json()["rows"]}
        assert tx_id not in ids

        # but visible with include_deleted=true
        r = await ac.get("/api/transactions?include_deleted=true")
        ids = {row["id"] for row in r.json()["rows"]}
        assert tx_id in ids

        # restore
        r = await ac.post(f"/api/transactions/{tx_id}/restore")
        assert r.status_code == 200

        r = await ac.get("/api/transactions")
        ids = {row["id"] for row in r.json()["rows"]}
        assert tx_id in ids


@pytest.mark.asyncio
async def test_rate_limit_enforced(w4_db, monkeypatch):
    from src import config, middleware
    monkeypatch.setattr(config, "ALLOWED_USERS", {5904148250})
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key-32-characters-long")
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")
    middleware._BUCKETS.clear()

    from src.main import app
    token = _make_jwt(5904148250)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"session": token}) as ac:
        # 30 calls allowed per minute → 31st should 429
        for i in range(30):
            r = await ac.post("/api/transactions",
                              json={"type": "spend", "amount_cents": 100,
                                    "source_wallet_id": 1,
                                    "occurred_at": "2026-05-10T12:00:00Z"})
            assert r.status_code == 201, f"{i}: {r.text}"
        r = await ac.post("/api/transactions",
                          json={"type": "spend", "amount_cents": 100,
                                "source_wallet_id": 1,
                                "occurred_at": "2026-05-10T12:00:00Z"})
        assert r.status_code == 429
