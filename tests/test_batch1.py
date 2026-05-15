"""Batch 1 — W5 wallet/place/item/alias writes, W11 language, W12 CSV."""
import csv
import io

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient


def _make_jwt(user_id: int) -> str:
    from src import auth, config
    config.SECRET_KEY = "test-secret-key-32-characters-long"
    return auth.create_session_token(user_id)


def _patch_for_auth(monkeypatch):
    from src import config, middleware
    monkeypatch.setattr(config, "ALLOWED_USERS", {5904148250})
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key-32-characters-long")
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")
    middleware._BUCKETS.clear()


# ---------- W5 wallet writes ----------

@pytest.mark.asyncio
async def test_insert_wallet_basic(w4_db):
    from src.writes import wallets as w
    wid = await w.insert_wallet(name_en="Vodafone", type="e_wallet", initial_balance_cents=500)
    assert wid > 0


@pytest.mark.asyncio
async def test_insert_wallet_gold_validates_karat(w4_db):
    from src.writes import wallets as w
    with pytest.raises(ValueError):
        await w.insert_wallet(name_en="Gold", type="asset_gold", karat=22)
    # karat 21 OK
    wid = await w.insert_wallet(name_en="Gold 21k", type="asset_gold", karat=21)
    assert wid > 0


@pytest.mark.asyncio
async def test_insert_wallet_unknown_type(w4_db):
    from src.writes import wallets as w
    with pytest.raises(ValueError):
        await w.insert_wallet(name_en="X", type="crypto")


@pytest.mark.asyncio
async def test_update_wallet_rejects_type_change(w4_db):
    from src.writes import wallets as w
    with pytest.raises(ValueError):
        await w.update_wallet(1, type="cash")  # not in allow-list


@pytest.mark.asyncio
async def test_update_wallet_name_persists(w4_db):
    from src.writes import wallets as w
    ok = await w.update_wallet(1, name_en="Bank (CIB renamed)")
    assert ok
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute("SELECT name_en FROM wallets WHERE id = 1") as cur:
            (name,) = await cur.fetchone()
    assert name == "Bank (CIB renamed)"


@pytest.mark.asyncio
async def test_wallet_soft_delete_and_restore(w4_db):
    from src.writes import wallets as w
    assert await w.soft_delete(1) is True
    assert await w.soft_delete(1) is False  # already deleted
    assert await w.restore(1) is True


# ---------- W5 place writes ----------

@pytest.mark.asyncio
async def test_update_place_unique_clash(w4_db):
    from src.writes import places as w
    # Make a second place, then try to rename it to clash with the first
    pid = await w.insert_place("Other Branch", "7-Eleven")
    with pytest.raises(ValueError):
        await w.update_place(pid, branch_name="7-Eleven Maadi", chain_name="7-Eleven")


@pytest.mark.asyncio
async def test_place_soft_delete_excludes_from_active(w4_db):
    from src.writes import places as w
    from src.queries import lookups
    assert await w.soft_delete(1) is True
    places = await lookups.places_list()
    assert all(p["id"] != 1 for p in places)


# ---------- W5 item writes ----------

@pytest.mark.asyncio
async def test_update_item_size(w4_db):
    from src.writes import items as w
    ok = await w.update_item(1, size="1L")
    assert ok
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute("SELECT size FROM items WHERE id = 1") as cur:
            (size,) = await cur.fetchone()
    assert size == "1L"


@pytest.mark.asyncio
async def test_alias_add_remove_idempotent(w4_db):
    from src.writes import items as w
    id1 = await w.add_alias(1, "S water")
    id2 = await w.add_alias(1, "S water")  # duplicate — returns same id
    assert id1 == id2
    assert await w.remove_alias(id1) is True
    assert await w.remove_alias(id1) is False  # already removed
    # Re-adding restores the soft-deleted row in-place
    id3 = await w.add_alias(1, "S water")
    assert id3 == id1


@pytest.mark.asyncio
async def test_update_item_adds_canonical_as_alias(w4_db):
    """Renaming an item's canonical should also expose the new name as a
    searchable alias so fuzzy search continues to find it."""
    from src.writes import items as w
    await w.update_item(1, canonical_name_en="Water 1L")
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute(
            "SELECT alias_text FROM item_aliases WHERE item_id = 1 AND deleted_at IS NULL"
        ) as cur:
            aliases = [r[0] for r in await cur.fetchall()]
    assert "Water 1L" in aliases


# ---------- W11 language ----------

@pytest.mark.asyncio
async def test_set_language_ar(w4_db):
    from src.writes import users as u
    ok = await u.set_language(5904148250, "ar")
    assert ok
    async with aiosqlite.connect(w4_db) as db:
        async with db.execute("SELECT language FROM users WHERE user_id = ?", (5904148250,)) as cur:
            (lang,) = await cur.fetchone()
    assert lang == "ar"


@pytest.mark.asyncio
async def test_set_language_invalid_rejected(w4_db):
    from src.writes import users as u
    with pytest.raises(ValueError):
        await u.set_language(5904148250, "fr")


@pytest.mark.asyncio
async def test_language_endpoint(w4_db, monkeypatch):
    _patch_for_auth(monkeypatch)
    from src.main import app
    token = _make_jwt(5904148250)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"session": token}) as ac:
        r = await ac.put("/api/me/language", json={"language": "ar"})
        assert r.status_code == 200, r.text
        r = await ac.put("/api/me/language", json={"language": "fr"})
        assert r.status_code == 400


# ---------- W12 CSV export ----------

@pytest.mark.asyncio
async def test_csv_export_header_and_rows(w4_db, monkeypatch):
    _patch_for_auth(monkeypatch)
    from src.writes import transactions as wt
    # Seed two transactions
    await wt.insert_transaction(type="spend", amount_cents=12345, source_wallet_id=1,
                                category_id=1, note='lunch, "with quotes"',
                                occurred_at="2026-05-10T12:00:00Z")
    await wt.insert_transaction(type="income", amount_cents=500000, dest_wallet_id=1,
                                occurred_at="2026-05-09T12:00:00Z")

    from src.main import app
    token = _make_jwt(5904148250)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"session": token}) as ac:
        r = await ac.get("/api/transactions/export.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        text = r.text
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == [
        "id", "date", "type", "amount_egp",
        "category", "item", "size", "place", "chain",
        "source_wallet", "dest_wallet", "note", "occurred_at_utc",
    ]
    # 2 data rows
    assert len(rows) == 3
    # Quoted note round-trips correctly
    notes = [r[11] for r in rows[1:]]
    assert 'lunch, "with quotes"' in notes
    # Amounts as X.YY decimal
    amounts = [r[3] for r in rows[1:]]
    assert "123.45" in amounts
    assert "5000.00" in amounts


@pytest.mark.asyncio
async def test_csv_export_respects_filter(w4_db, monkeypatch):
    _patch_for_auth(monkeypatch)
    from src.writes import transactions as wt
    await wt.insert_transaction(type="spend", amount_cents=100, source_wallet_id=1,
                                occurred_at="2026-05-10T12:00:00Z")
    await wt.insert_transaction(type="income", amount_cents=200, dest_wallet_id=1,
                                occurred_at="2026-05-10T12:00:00Z")

    from src.main import app
    token = _make_jwt(5904148250)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"session": token}) as ac:
        r = await ac.get("/api/transactions/export.csv?type=income")
        rows = list(csv.reader(io.StringIO(r.text)))
    assert len(rows) == 2  # header + 1 income
    assert rows[1][2] == "income"
